# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This System Does

This is an **autonomous multi-agent income generation system**. Seven specialized AI agents run on a daily schedule, each independently researching trends, generating content/products, and publishing to real-world platforms (Gumroad, Amazon KDP, Etsy, Shopify, stock image sites, Upwork, Yelp). Revenue and outputs are tracked in a unified dashboard with a $1,000 goal.

**Agents and their platforms:**
- `youtube` — Reddit trend research → video scripts + thumbnail concepts
- `kdp` — Ebook/workbook manuscript generation → Amazon KDP PDF
- `newsletter` — Full HTML + plain-text newsletter issues
- `stock_images` — AI image prompts + submission CSV metadata
- `print_on_demand` — Typography design briefs + PIL-generated PNGs
- `local_leads` — Yelp scraping → cold-email lead lists
- `freelance` — Upwork job scraping → personalized proposals

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run all agents
python orchestrate.py

# Run a single named agent
python orchestrate.py youtube
python orchestrate.py kdp

# List agents and their last run times
python orchestrate.py --list

# Show revenue dashboard only
python orchestrate.py --dashboard

# Legacy product agent (Gumroad digital products)
python run.py
python run.py --count 2
python run.py --dry-run
python run.py --sales
```

There is **no test suite**. Validation is done by inspecting generated outputs under `outputs/`.

## Architecture

### Key Directories

- `orchestrate.py` — Master entry point; dynamically imports and runs agents from `AGENT_REGISTRY`
- `agents/{name}/agent.py` — One file per agent; each is self-contained (research + generate + publish + track)
- `shared/` — Utilities shared by all agents: LLM client, tracker, file/web helpers
- `agent/` — Legacy product agent (Gumroad); uses its own internal modules, largely superseded
- `brand/config.py` — "RISE SUPPLY CO." brand settings (colors, tagline, pricing, Shopify collections)
- `data/` — Persistent JSON state: `revenue.json`, `run_log.json`, `{agent}_state.json`
- `outputs/` — All generated content, organized as `outputs/{agent}/YYYY-MM-DD/`
- `templates/niches.json` — Curated niche/topic pool (~15 niches, 500+ topics) used by legacy agent

### LLM Client (`shared/claude_client.py`)

All LLM calls go through this module. It abstracts two providers:

1. **Groq** (preferred — free tier, ~14.4k req/day): `llama-3.3-70b-versatile` (smart), `llama-3.1-8b-instant` (fast)
2. **Anthropic** (fallback): `claude-sonnet-4-6` (smart), `claude-haiku-4-5-20251001` (fast)

At least one of `GROQ_API_KEY` or `ANTHROPIC_API_KEY` must be set; if neither is present it raises `EnvironmentError`.

```python
from shared.claude_client import generate, generate_json

text = generate(prompt, system="...", max_tokens=500, smart=False)
data = generate_json(prompt, system="...", max_tokens=500)  # auto-strips markdown, parses JSON
```

### Agent Contract

Every agent in `agents/{name}/agent.py` exports a single `run()` function:

```python
def run(config: dict | None = None) -> dict:
    # Returns:
    # { "status": "success"|"error"|"skipped",
    #   "outputs": [{"title": str, "path": str, ...}],
    #   "error": str }  # only on error
```

`orchestrate.py` loads agents via `importlib.import_module()` using `AGENT_REGISTRY` and calls `run()`. If one agent raises, others continue; a run summary is printed at the end.

### Standard Shared Utilities

```python
from shared.tracker import log_output        # records output + revenue to data/
from shared.utils import (
    slugify,          # "My Title" → "my-title"
    save_text,        # write str to file
    save_json,        # write dict to JSON file
    fetch_page,       # requests + BeautifulSoup HTML fetch
    fetch_reddit_titles,  # scrape r/{sub} post titles
    datestamp,        # returns "YYYY-MM-DD"
)
```

### Output Organization

Every agent writes its files to `outputs/{agent_name}/{datestamp()}/`. State that persists across runs (topics already used, last run time, cumulative revenue) lives in `data/{agent}_state.json`.

## Environment Variables

```bash
# Required — at least one:
GROQ_API_KEY=gsk_...
ANTHROPIC_API_KEY=sk-ant-...

# Agent-specific (only needed for those agents):
GUMROAD_ACCESS_TOKEN=...
PRINTIFY_API_KEY=...
SHOPIFY_STORE_URL=...
SHOPIFY_API_TOKEN=...

# Optional:
AUTHOR_NAME=Your Name
```

Copy `.env.example` to `.env` for local development.

## CI/CD (GitHub Actions)

- `.github/workflows/agents.yml` — Primary workflow; runs all agents daily at 8 AM UTC (or via manual dispatch). Uses repository secrets for all API keys. After running, commits new outputs to the current branch with `git commit -m "chore: agent outputs YYYY-MM-DD"`.
- `.github/workflows/daily-agent.yml` — Legacy workflow for the old `agent/` product agent; effectively replaced by `agents.yml`.

## Adding a New Agent

1. Create `agents/{name}/agent.py` implementing `run() -> dict`
2. Add `"{name}": "agents.{name}.agent"` to `AGENT_REGISTRY` in `orchestrate.py`
3. Use `shared/claude_client.py` for all LLM calls; use `shared/tracker.log_output()` to record results
4. Write outputs to `outputs/{name}/{datestamp()}/` using `save_text` / `save_json`
5. Persist cross-run state in `data/{name}_state.json`
6. Add any new API keys to `.env.example` and the GitHub Actions secrets
