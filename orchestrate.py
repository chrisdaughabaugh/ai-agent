"""Master orchestrator for the autonomous income-generating multi-agent system.

Usage
-----
    python orchestrate.py                  # run all agents
    python orchestrate.py youtube          # run a single agent by name
    python orchestrate.py --list           # list agents and last run times
    python orchestrate.py --dashboard      # show revenue dashboard only
"""

import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Bootstrap: ensure repo root is on sys.path
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ---------------------------------------------------------------------------
# Load .env early so all agents inherit the environment
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass  # python-dotenv optional; rely on shell environment

# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------
from shared.tracker import print_dashboard

DATA_DIR = ROOT / "data"
RUN_LOG_FILE = DATA_DIR / "run_log.json"

# ---------------------------------------------------------------------------
# Agent registry
# ---------------------------------------------------------------------------

AGENT_REGISTRY = {
    "youtube": "agents.youtube.agent",
    "kdp": "agents.kdp.agent",
    "newsletter": "agents.newsletter.agent",
    "stock_images": "agents.stock_images.agent",
    "print_on_demand": "agents.print_on_demand.agent",
    "local_leads": "agents.local_leads.agent",
    "freelance": "agents.freelance.agent",
}

# Human-readable descriptions shown by --list
AGENT_DESCRIPTIONS = {
    "youtube": "YouTube script & thumbnail ideas generator",
    "kdp": "Kindle Direct Publishing ebook creator",
    "newsletter": "Newsletter content + issue generator",
    "stock_images": "AI stock image prompt & metadata creator",
    "print_on_demand": "Print-on-demand design brief generator",
    "local_leads": "Local business lead generation (Yelp → cold email)",
    "freelance": "Freelance proposal & gig content generator",
}

# Required environment variables per agent (empty list = none required beyond ANTHROPIC_API_KEY)
AGENT_REQUIRED_ENV = {
    "youtube": [],
    "kdp": [],
    "newsletter": [],
    "stock_images": [],
    "print_on_demand": [],
    "local_leads": [],
    "freelance": [],
}

# ---------------------------------------------------------------------------
# Run-log helpers
# ---------------------------------------------------------------------------

def _load_run_log() -> dict:
    if RUN_LOG_FILE.exists():
        with open(RUN_LOG_FILE) as f:
            return json.load(f)
    return {"runs": []}


def _save_run_log(log: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(RUN_LOG_FILE, "w") as f:
        json.dump(log, f, indent=2, default=str)


def _log_run(agent_name: str, result: dict, error: str = ""):
    log = _load_run_log()
    entry = {
        "agent": agent_name,
        "timestamp": datetime.now().isoformat(),
        "status": result.get("status", "error") if not error else "error",
        "outputs": result.get("outputs", []) if not error else [],
        "error": error,
    }
    # Carry through any extra scalar fields the agent returns
    for k, v in result.items():
        if k not in entry and isinstance(v, (str, int, float, bool)):
            entry[k] = v
    log["runs"].append(entry)
    _save_run_log(log)
    return entry


def _last_run_time(agent_name: str) -> str:
    log = _load_run_log()
    runs = [r for r in log.get("runs", []) if r.get("agent") == agent_name]
    if not runs:
        return "never"
    last = runs[-1]
    ts = last.get("timestamp", "")
    status = last.get("status", "?")
    return f"{ts[:19]}  [{status}]"


# ---------------------------------------------------------------------------
# Dependency / environment checks
# ---------------------------------------------------------------------------

def _check_env() -> list[str]:
    """Return list of missing critical environment variables."""
    missing = []
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing.append("ANTHROPIC_API_KEY")
    return missing


def _check_agent_env(agent_name: str) -> list[str]:
    """Return missing env vars specific to a given agent."""
    missing = []
    for var in AGENT_REQUIRED_ENV.get(agent_name, []):
        if not os.environ.get(var):
            missing.append(var)
    return missing


def _ensure_directories():
    """Create standard output directories if they don't exist."""
    dirs = [
        ROOT / "data",
        ROOT / "outputs" / "youtube",
        ROOT / "outputs" / "books",
        ROOT / "outputs" / "newsletters",
        ROOT / "outputs" / "stock_images",
        ROOT / "outputs" / "designs",
        ROOT / "outputs" / "leads",
        ROOT / "outputs" / "proposals",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Dynamic agent import + run
# ---------------------------------------------------------------------------

def _import_run(module_path: str):
    """Dynamically import a module and return its run() function."""
    import importlib
    mod = importlib.import_module(module_path)
    return mod.run


def _run_agent(agent_name: str, config: dict | None = None) -> dict:
    """
    Run a single agent by name.

    Returns the agent's result dict, or a synthetic error dict if anything
    goes wrong (import error, runtime exception, etc.).
    """
    module_path = AGENT_REGISTRY[agent_name]

    # Check agent-specific env vars
    missing = _check_agent_env(agent_name)
    if missing:
        msg = f"Missing environment variables for {agent_name}: {', '.join(missing)}"
        print(f"[orchestrate] WARNING: {msg} — skipping agent.")
        result = {"status": "skipped", "outputs": [], "reason": msg}
        _log_run(agent_name, result)
        return result

    print(f"\n[orchestrate] ===== Running agent: {agent_name} =====")
    try:
        run_fn = _import_run(module_path)
    except ImportError as exc:
        msg = f"Could not import {module_path}: {exc}"
        print(f"[orchestrate] ERROR: {msg}")
        result = {"status": "error", "outputs": [], "error": msg}
        _log_run(agent_name, result, error=msg)
        return result

    try:
        result = run_fn(config) if config is not None else run_fn()
        if not isinstance(result, dict):
            result = {"status": "success", "outputs": []}
        result.setdefault("status", "success")
        result.setdefault("outputs", [])
    except Exception:
        tb = traceback.format_exc()
        msg = tb.strip().splitlines()[-1]
        print(f"[orchestrate] ERROR in {agent_name}:\n{tb}")
        result = {"status": "error", "outputs": [], "error": msg}
        _log_run(agent_name, result, error=msg)
        return result

    _log_run(agent_name, result)
    status_str = result.get("status", "?")
    outputs = result.get("outputs", [])
    print(f"[orchestrate] {agent_name} finished — status={status_str}, "
          f"{len(outputs)} output(s)")
    return result


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

def cmd_list():
    """Print all registered agents and their last run time."""
    print("\n{:<18} {:<42} {}".format("AGENT", "DESCRIPTION", "LAST RUN"))
    print("-" * 80)
    for name in AGENT_REGISTRY:
        desc = AGENT_DESCRIPTIONS.get(name, "")
        last = _last_run_time(name)
        print(f"{name:<18} {desc:<42} {last}")
    print()


def cmd_dashboard():
    """Show the combined revenue / activity dashboard."""
    print_dashboard()

    # Also show run-log summary
    log = _load_run_log()
    runs = log.get("runs", [])
    if not runs:
        print("  No run history yet.\n")
        return

    print("  RECENT RUNS (last 20)")
    print("  " + "-" * 54)
    for r in runs[-20:]:
        ts = r.get("timestamp", "")[:19]
        agent = r.get("agent", "?")
        status = r.get("status", "?")
        n_out = len(r.get("outputs", []))
        err = r.get("error", "")
        line = f"  {ts}  {agent:<16} {status:<8} {n_out} output(s)"
        if err:
            line += f"  ERR: {err[:40]}"
        print(line)
    print()


def cmd_run_all():
    """Run every registered agent in order, catching per-agent errors."""
    results = {}
    for name in AGENT_REGISTRY:
        results[name] = _run_agent(name)
    _summarise_results(results)
    return results


def cmd_run_one(agent_name: str):
    """Run a single named agent."""
    if agent_name not in AGENT_REGISTRY:
        available = ", ".join(AGENT_REGISTRY.keys())
        print(f"[orchestrate] Unknown agent '{agent_name}'. Available: {available}")
        sys.exit(1)
    result = _run_agent(agent_name)
    _summarise_results({agent_name: result})
    return result


def _summarise_results(results: dict):
    print("\n[orchestrate] ===== RUN SUMMARY =====")
    ok = [n for n, r in results.items() if r.get("status") == "success"]
    skipped = [n for n, r in results.items() if r.get("status") == "skipped"]
    errored = [n for n, r in results.items() if r.get("status") == "error"]
    total_outputs = sum(len(r.get("outputs", [])) for r in results.values())
    print(f"  Succeeded : {len(ok)}  —  {', '.join(ok) or 'none'}")
    print(f"  Skipped   : {len(skipped)}  —  {', '.join(skipped) or 'none'}")
    print(f"  Errored   : {len(errored)}  —  {', '.join(errored) or 'none'}")
    print(f"  Total outputs produced: {total_outputs}")
    print_dashboard()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Multi-agent income system orchestrator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python orchestrate.py                 # run all agents\n"
            "  python orchestrate.py youtube         # run just youtube agent\n"
            "  python orchestrate.py --list          # show agents & last run\n"
            "  python orchestrate.py --dashboard     # revenue dashboard only\n"
        ),
    )
    parser.add_argument(
        "agent",
        nargs="?",
        default=None,
        help="Name of a single agent to run (omit to run all)",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all agents and their last run times",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Show revenue dashboard only (no agents run)",
    )
    args = parser.parse_args()

    # --- Global env check ---------------------------------------------------
    missing_global = _check_env()
    if missing_global:
        print(f"[orchestrate] FATAL: Missing required environment variables: "
              f"{', '.join(missing_global)}")
        print("  Set them in your .env file or export them before running.")
        sys.exit(1)

    _ensure_directories()

    # --- Dispatch -----------------------------------------------------------
    if args.list:
        cmd_list()
    elif args.dashboard:
        cmd_dashboard()
    elif args.agent:
        cmd_run_one(args.agent)
    else:
        cmd_run_all()


if __name__ == "__main__":
    main()
