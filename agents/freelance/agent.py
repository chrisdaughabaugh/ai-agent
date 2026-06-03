"""
Freelance Proposal Bot
Scrapes Upwork RSS feeds, filters relevant jobs, and generates
personalized proposals using Claude.
"""

import sys
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional

# Allow importing from shared/
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared.claude_client import generate, generate_json
from shared.tracker import log_output
from shared.utils import slugify, fetch_page, save_text, save_json, today_dir, datestamp

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AGENT_NAME = "freelance"
BASE_DIR = Path(__file__).parent.parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUTS_DIR = BASE_DIR / "outputs" / "proposals"
STATE_FILE = DATA_DIR / "freelance_state.json"

MAX_PROPOSALS_PER_RUN = 5
BUDGET_MINIMUM_USD = 50
MAX_AGE_HOURS = 6

TARGET_KEYWORDS = [
    "AI writing",
    "content writing",
    "copywriting",
    "blog posts",
    "social media content",
    "email marketing",
    "ChatGPT",
    "AI assistant",
]

UPWORK_RSS_BASE = "https://www.upwork.com/ab/feed/jobs/rss"

SYSTEM_PROMPT = (
    "You are an expert freelance writer and AI consultant with 8+ years of experience. "
    "You write compelling, personalized Upwork proposals that win contracts. "
    "Your proposals are direct, confident, and reference the client's specific needs. "
    "When asked for JSON, respond with valid JSON only — no markdown fences, no commentary."
)

# ---------------------------------------------------------------------------
# State helpers
# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"applied_job_ids": [], "total_proposals": 0, "runs": []}


def save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# RSS scraping
# ---------------------------------------------------------------------------

def build_rss_url(keyword: str) -> str:
    from urllib.parse import urlencode
    params = {"q": keyword, "sort": "recency"}
    return f"{UPWORK_RSS_BASE}?{urlencode(params)}"


def parse_rss_jobs(xml_text: str) -> list[dict]:
    """Parse Upwork RSS XML and return list of job dicts."""
    jobs: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"    [WARN] XML parse error: {e}")
        return jobs

    # Namespace handling — Upwork uses standard RSS 2.0
    channel = root.find("channel")
    if channel is None:
        return jobs

    for item in channel.findall("item"):
        def tag(name: str) -> str:
            el = item.find(name)
            return el.text.strip() if el is not None and el.text else ""

        title = tag("title")
        link = tag("link")
        description = tag("description")
        pub_date_str = tag("pubDate")
        guid = tag("guid") or link

        # Parse budget from description text
        budget = extract_budget(description)

        # Parse publication date
        pub_dt = parse_pub_date(pub_date_str)

        jobs.append({
            "id": guid,
            "title": title,
            "link": link,
            "description": clean_html(description),
            "pub_date": pub_date_str,
            "pub_dt": pub_dt.isoformat() if pub_dt else None,
            "budget_usd": budget,
        })

    return jobs


def clean_html(text: str) -> str:
    """Strip HTML tags from description text."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_budget(description: str) -> Optional[float]:
    """Try to extract a numeric budget from Upwork description text."""
    import re
    # Patterns like "$500", "Budget: $200", "Fixed-Price: $1,500"
    patterns = [
        r"\$\s?([\d,]+(?:\.\d+)?)",
        r"budget[:\s]+\$?\s?([\d,]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, description, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                continue
    return None


def parse_pub_date(date_str: str) -> Optional[datetime]:
    """Parse RFC 2822 date from RSS pubDate field."""
    if not date_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%d %b %Y %H:%M:%S %z",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    # Fallback: try dateutil if available
    try:
        from dateutil import parser as dateutil_parser
        return dateutil_parser.parse(date_str)
    except Exception:
        return None


def is_recent(pub_dt_str: Optional[str], max_hours: int = MAX_AGE_HOURS) -> bool:
    """Return True if the job was posted within max_hours."""
    if not pub_dt_str:
        return True  # can't verify — include it
    try:
        pub_dt = datetime.fromisoformat(pub_dt_str)
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_hours)
        return pub_dt >= cutoff
    except Exception:
        return True


def scrape_jobs() -> list[dict]:
    """Fetch jobs from all keyword RSS feeds."""
    all_jobs: list[dict] = []
    seen_ids: set[str] = set()

    for keyword in TARGET_KEYWORDS:
        url = build_rss_url(keyword)
        print(f"  Fetching RSS: {keyword!r}")
        xml_text = fetch_page(url, timeout=12)
        if not xml_text:
            print(f"    [WARN] No response for keyword '{keyword}'")
            continue

        jobs = parse_rss_jobs(xml_text)
        print(f"    Found {len(jobs)} items")

        for job in jobs:
            if job["id"] not in seen_ids:
                seen_ids.add(job["id"])
                job["keyword_source"] = keyword
                all_jobs.append(job)

    return all_jobs


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_jobs(jobs: list[dict], applied_ids: list[str]) -> list[dict]:
    """Keep jobs that pass budget, recency, and novelty filters."""
    applied_set = set(applied_ids)
    filtered: list[dict] = []

    for job in jobs:
        job_id = job.get("id", "")

        # Already applied
        if job_id in applied_set:
            continue

        # Recency check
        if not is_recent(job.get("pub_dt"), max_hours=MAX_AGE_HOURS):
            continue

        # Budget check — include if budget unknown (may be hourly/unlisted)
        budget = job.get("budget_usd")
        if budget is not None and budget < BUDGET_MINIMUM_USD:
            continue

        filtered.append(job)

    # Sort by most recent first (jobs with no date go last)
    def sort_key(j):
        dt_str = j.get("pub_dt") or ""
        return dt_str

    filtered.sort(key=sort_key, reverse=True)
    return filtered[:MAX_PROPOSALS_PER_RUN]


# ---------------------------------------------------------------------------
# Claude: generate proposal
# ---------------------------------------------------------------------------

def generate_proposal(job: dict) -> dict:
    """Use Claude to produce a full proposal package for a job."""
    title = job.get("title", "this project")
    description = job.get("description", "")[:1200]  # trim to save tokens
    keyword_source = job.get("keyword_source", "freelance writing")

    prompt = f"""A client posted this job on Upwork:

TITLE: {title}

DESCRIPTION:
{description}

I am applying as a freelance AI writing and content specialist. Generate a complete proposal package.

Return a JSON object with exactly these keys:
{{
  "proposal": "A 200-300 word personalized proposal. Open with a hook that shows I read their post carefully. Mention 1-2 specific things from their description. Show relevant experience (AI-assisted content, blog writing, SEO copy, email sequences, social media). Include a clear CTA asking to hop on a quick call or start with a small paid trial. First person, warm but professional tone.",
  "experience_snippet": "A 2-3 sentence 'relevant experience' blurb tailored to this specific job type. Reference concrete deliverables like word count, engagement metrics, or turnaround times.",
  "estimated_timeline": "Realistic timeline for this project scope (e.g. '3-5 business days for initial draft').",
  "suggested_price_range": "A price range appropriate for this job. If fixed-price job, give a range like '$150-$250'. If hourly, give '$35-$55/hr'.",
  "bid_strategy": "One sentence on why this price is competitive and how to position it."
}}

Rules:
- The proposal must feel hand-written, not generic. Reference the job title or specifics.
- Do NOT use phrases like 'I noticed you're looking for' or 'As an AI language model'.
- Keep the tone confident and results-focused.
- The experience_snippet should NOT repeat the opening of the proposal."""

    return generate_json(prompt, system=SYSTEM_PROMPT, max_tokens=1400, smart=True)


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

PROPOSAL_FILE_TEMPLATE = """\
UPWORK PROPOSAL — {date}
========================

JOB: {title}
URL: {link}
POSTED: {pub_date}
BUDGET: {budget}
SOURCE KEYWORD: {keyword_source}

--- PROPOSAL (copy into Upwork cover letter) ---

{proposal}

--- RELEVANT EXPERIENCE SNIPPET ---

{experience_snippet}

--- TIMELINE ---

{estimated_timeline}

--- SUGGESTED PRICE RANGE ---

{suggested_price_range}

--- BID STRATEGY ---

{bid_strategy}
"""

SUMMARY_TEMPLATE = """\
FREELANCE PROPOSAL SUMMARY — {date}
=====================================
Run completed: {timestamp}
Total jobs scraped: {total_scraped}
Jobs passing filters: {jobs_filtered}
Proposals generated: {proposals_count}

---

{entries}

---
Next steps:
1. Open each proposal file in outputs/proposals/{date}/
2. Review and personalize if needed (add client name, tweak specifics)
3. Submit on Upwork within the next 2 hours for best visibility
4. Follow up after 48 hours if no response
"""

SUMMARY_ENTRY = """\
[{num}] {title}
    URL: {link}
    Budget: {budget}
    File: {filename}
"""


def format_budget(job: dict) -> str:
    budget = job.get("budget_usd")
    if budget:
        return f"${budget:,.0f}"
    return "Not listed (hourly or unspecified)"


def build_proposal_file(job: dict, proposal_data: dict) -> str:
    return PROPOSAL_FILE_TEMPLATE.format(
        date=datestamp(),
        title=job.get("title", ""),
        link=job.get("link", ""),
        pub_date=job.get("pub_date", ""),
        budget=format_budget(job),
        keyword_source=job.get("keyword_source", ""),
        proposal=proposal_data.get("proposal", ""),
        experience_snippet=proposal_data.get("experience_snippet", ""),
        estimated_timeline=proposal_data.get("estimated_timeline", ""),
        suggested_price_range=proposal_data.get("suggested_price_range", ""),
        bid_strategy=proposal_data.get("bid_strategy", ""),
    )


def make_job_slug(job: dict, index: int) -> str:
    """Create a short filename-safe ID from job data."""
    title_slug = slugify(job.get("title", f"job-{index}"), max_len=40)
    # Try to extract a numeric ID from the Upwork URL or GUID
    import re
    link = job.get("link", "") or job.get("id", "")
    match = re.search(r"~(\w+)", link)
    short_id = match.group(1)[:10] if match else str(index).zfill(3)
    return f"{title_slug}-{short_id}"


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run():
    print(f"\n[Freelance Agent] Starting run — {datestamp()}")

    state = load_state()
    applied_ids = state.get("applied_job_ids", [])

    # 1. Scrape
    print("\n[1/4] Scraping Upwork RSS feeds...")
    all_jobs = scrape_jobs()
    print(f"  Total unique jobs scraped: {len(all_jobs)}")

    # 2. Filter
    print("\n[2/4] Filtering jobs...")
    candidate_jobs = filter_jobs(all_jobs, applied_ids)
    print(f"  Jobs passing filters: {len(candidate_jobs)}")

    if not candidate_jobs:
        print("  [INFO] No qualifying jobs found this run. Try again in a few hours.")
        # Still save what we found
        out_dir = today_dir(OUTPUTS_DIR)
        save_json(out_dir / "jobs_found.json", {
            "date": datestamp(),
            "total_scraped": len(all_jobs),
            "jobs_filtered": 0,
            "all_jobs": all_jobs,
        })
        return

    # 3. Generate proposals
    print(f"\n[3/4] Generating proposals for {len(candidate_jobs)} job(s)...")
    out_dir = today_dir(OUTPUTS_DIR)
    generated: list[dict] = []

    for i, job in enumerate(candidate_jobs, 1):
        print(f"\n  Job {i}/{len(candidate_jobs)}: {job.get('title', '')[:70]}")
        try:
            proposal_data = generate_proposal(job)
        except Exception as e:
            print(f"  [ERROR] Proposal generation failed: {e}")
            continue

        job_slug = make_job_slug(job, i)
        filename = f"proposal-{job_slug}.txt"
        proposal_text = build_proposal_file(job, proposal_data)
        proposal_path = out_dir / filename
        save_text(proposal_path, proposal_text)
        print(f"  Saved: {filename}")

        log_output(
            AGENT_NAME,
            job.get("title", f"job-{i}"),
            str(proposal_path),
            notes=(
                f"keyword={job.get('keyword_source', '')}, "
                f"budget={format_budget(job)}"
            ),
        )

        generated.append({
            "job": job,
            "proposal": proposal_data,
            "filename": filename,
            "path": str(proposal_path),
        })

        # Mark as applied in state immediately to avoid duplicates mid-run
        applied_ids.append(job["id"])

    # 4. Save aggregate outputs
    print("\n[4/4] Saving aggregate outputs...")

    # jobs_found.json
    jobs_json_path = out_dir / "jobs_found.json"
    save_json(jobs_json_path, {
        "date": datestamp(),
        "total_scraped": len(all_jobs),
        "jobs_filtered": len(candidate_jobs),
        "proposals_generated": len(generated),
        "all_jobs": all_jobs,
        "candidate_jobs": candidate_jobs,
    })
    print(f"  Saved jobs_found.json -> {jobs_json_path}")

    # proposals_summary.txt
    entries = ""
    for i, item in enumerate(generated, 1):
        j = item["job"]
        entries += SUMMARY_ENTRY.format(
            num=i,
            title=j.get("title", ""),
            link=j.get("link", ""),
            budget=format_budget(j),
            filename=item["filename"],
        )

    summary_text = SUMMARY_TEMPLATE.format(
        date=datestamp(),
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        total_scraped=len(all_jobs),
        jobs_filtered=len(candidate_jobs),
        proposals_count=len(generated),
        entries=entries if entries else "  (none generated)",
    )
    summary_path = out_dir / "proposals_summary.txt"
    save_text(summary_path, summary_text)
    print(f"  Saved proposals_summary.txt -> {summary_path}")

    # Update state
    state["applied_job_ids"] = applied_ids[-500:]  # keep last 500 to avoid unbounded growth
    state["total_proposals"] = state.get("total_proposals", 0) + len(generated)
    state["runs"].append({
        "date": datestamp(),
        "jobs_scraped": len(all_jobs),
        "jobs_filtered": len(candidate_jobs),
        "proposals_generated": len(generated),
        "output_dir": str(out_dir),
    })
    save_state(state)

    print(f"\n[Freelance Agent] Done. {len(generated)} proposal(s) saved to {out_dir}\n")


if __name__ == "__main__":
    run()
