"""Unified revenue and activity tracker across all agents."""

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

DATA_FILE = Path(__file__).parent.parent / "data" / "revenue.json"


def _load() -> dict:
    if DATA_FILE.exists():
        with open(DATA_FILE) as f:
            return json.load(f)
    return {"agents": {}, "total_revenue_cents": 0, "last_updated": ""}


def _save(data: dict):
    DATA_FILE.parent.mkdir(exist_ok=True)
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2, default=str)


def log_output(agent_name: str, title: str, output_path: str, notes: str = ""):
    """Log that an agent produced an output asset."""
    data = _load()
    if agent_name not in data["agents"]:
        data["agents"][agent_name] = {"outputs": [], "revenue_cents": 0}
    data["agents"][agent_name]["outputs"].append({
        "title": title,
        "path": output_path,
        "notes": notes,
        "created_at": datetime.now().isoformat(),
        "revenue_cents": 0,
    })
    data["last_updated"] = datetime.now().isoformat()
    _save(data)


def log_revenue(agent_name: str, amount_cents: int, source: str = ""):
    """Record revenue from a sale."""
    data = _load()
    if agent_name not in data["agents"]:
        data["agents"][agent_name] = {"outputs": [], "revenue_cents": 0}
    data["agents"][agent_name]["revenue_cents"] += amount_cents
    data["total_revenue_cents"] += amount_cents
    data["last_updated"] = datetime.now().isoformat()
    _save(data)


def print_dashboard():
    data = _load()
    total = data.get("total_revenue_cents", 0)
    goal = 100000  # $1000
    pct = min(100, round((total / goal) * 100, 1))
    bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))

    print("\n" + "=" * 56)
    print("  MULTI-AGENT REVENUE DASHBOARD")
    print("=" * 56)
    print(f"  Total revenue  : ${total/100:.2f}")
    print(f"  $1000 goal     : [{bar}] {pct}%")
    print()
    for name, info in data.get("agents", {}).items():
        rev = info.get("revenue_cents", 0)
        count = len(info.get("outputs", []))
        print(f"  {name:<22} ${rev/100:>7.2f}  ({count} outputs)")
    print("=" * 56 + "\n")
