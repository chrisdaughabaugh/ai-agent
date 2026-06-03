"""Local Business Lead Generation Agent.

Scrapes Yelp for local businesses lacking a website or with a poor web
presence, then uses Claude to write personalised cold-outreach emails.

Run interface
-------------
    from agents.local_leads.agent import run
    result = run()                          # rotate through city/category
    result = run({"city": "Austin TX", "category": "plumbers"})
"""

import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote_plus, urlparse

# ---------------------------------------------------------------------------
# Bootstrap: make sure the repo root is on sys.path so shared/ resolves
# ---------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bs4 import BeautifulSoup

from shared.claude_client import generate, generate_json
from shared.tracker import log_output
from shared.utils import fetch_page, save_json, save_text, slugify, today_dir

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

US_CITIES = [
    "Austin TX", "Nashville TN", "Denver CO", "Portland OR", "Charlotte NC",
    "Indianapolis IN", "Columbus OH", "San Antonio TX", "Jacksonville FL",
    "Memphis TN", "Louisville KY", "Baltimore MD", "Milwaukee WI",
    "Albuquerque NM", "Tucson AZ", "Fresno CA", "Sacramento CA",
    "Mesa AZ", "Omaha NE", "Raleigh NC", "Colorado Springs CO",
    "Virginia Beach VA", "Long Beach CA", "Minneapolis MN", "Tampa FL",
    "New Orleans LA", "Arlington TX", "Bakersfield CA", "Honolulu HI",
    "Anaheim CA", "Aurora CO", "Santa Ana CA", "Corpus Christi TX",
    "Riverside CA", "St. Louis MO", "Lexington KY", "Pittsburgh PA",
    "Stockton CA", "Anchorage AK", "Cincinnati OH", "St. Paul MN",
    "Greensboro NC", "Toledo OH", "Newark NJ", "Plano TX",
    "Henderson NV", "Lincoln NE", "Buffalo NY", "Fort Wayne IN",
    "Jersey City NJ", "Chula Vista CA", "Orlando FL", "St. Petersburg FL",
    "Norfolk VA", "Chandler AZ", "Laredo TX", "Madison WI",
    "Durham NC", "Lubbock TX", "Winston-Salem NC", "Garland TX",
    "Glendale AZ", "Hialeah FL", "Reno NV", "Baton Rouge LA",
    "Irvine CA", "Chesapeake VA", "Scottsdale AZ", "North Las Vegas NV",
    "Fremont CA", "Gilbert AZ", "San Bernardino CA", "Boise ID",
    "Birmingham AL", "Rochester NY", "Richmond VA", "Spokane WA",
    "Des Moines IA", "Montgomery AL", "Modesto CA", "Fayetteville NC",
    "Tacoma WA", "Shreveport LA", "Akron OH", "Aurora IL", "Yonkers NY",
    "Huntington Beach CA", "Little Rock AR", "Glendale CA",
    "Columbus GA", "Salt Lake City UT", "Tallahassee FL",
    "Huntsville AL", "Worcester MA", "Knoxville TN",
    "Providence RI", "Grand Rapids MI", "Oxnard CA",
]

CATEGORIES = [
    "restaurants", "plumbers", "electricians", "hair salons",
    "cleaning services", "landscaping", "personal trainers",
    "photographers", "yoga studios", "dentists",
]

OUTPUTS_BASE = ROOT / "outputs" / "leads"
DATA_DIR = ROOT / "data"
STATE_FILE = DATA_DIR / "leads_state.json"

YELP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PRICE_RANGE = "$299–$499"
MAX_TARGETS_PER_RUN = 10


# ---------------------------------------------------------------------------
# State helpers (rotation)
# ---------------------------------------------------------------------------

def _load_state() -> dict:
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"city_index": 0, "category_index": 0, "runs": []}


def _save_state(state: dict):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _next_city_category(state: dict) -> tuple[str, str]:
    ci = state.get("city_index", 0) % len(US_CITIES)
    cati = state.get("category_index", 0) % len(CATEGORIES)
    city = US_CITIES[ci]
    category = CATEGORIES[cati]
    # Advance: cycle through all categories for each city before moving on
    new_cati = (cati + 1) % len(CATEGORIES)
    if new_cati == 0:
        state["city_index"] = (ci + 1) % len(US_CITIES)
    state["category_index"] = new_cati
    return city, category


# ---------------------------------------------------------------------------
# Yelp scraping
# ---------------------------------------------------------------------------

def _yelp_url(category: str, city: str) -> str:
    return (
        f"https://www.yelp.com/search"
        f"?find_desc={quote_plus(category)}&find_loc={quote_plus(city)}"
    )


def _parse_yelp_html(html: str) -> list[dict]:
    """Extract business cards from a Yelp SERP page."""
    soup = BeautifulSoup(html, "html.parser")
    businesses = []

    # Yelp renders results inside <li> or <div> blocks that contain a link to
    # /biz/.  We find all anchor tags pointing at /biz/ and walk up to the
    # enclosing card-like container.
    biz_links = soup.find_all("a", href=re.compile(r"^/biz/"))
    seen_hrefs = set()

    for link in biz_links:
        href = link.get("href", "")
        # Deduplicate: multiple anchors can point at the same biz
        biz_slug = href.split("?")[0]
        if biz_slug in seen_hrefs:
            continue
        seen_hrefs.add(biz_slug)

        # Walk up to a container that is large enough to hold all card data
        card = link
        for _ in range(8):
            card = card.parent
            if card is None:
                break
            text = card.get_text(" ", strip=True)
            # A valid card contains a rating or review count
            if re.search(r"\d+\.\d|\d+ review", text, re.I):
                break

        if card is None:
            continue

        card_text = card.get_text(" ", strip=True)

        # Business name — the link text itself is usually the name
        name = link.get_text(strip=True)
        if not name or len(name) < 2:
            continue

        # Rating
        rating_match = re.search(r"(\d+\.\d)", card_text)
        rating = rating_match.group(1) if rating_match else ""

        # Review count
        review_match = re.search(r"(\d+)\s+review", card_text, re.I)
        review_count = review_match.group(1) if review_match else "0"

        # Phone  (Yelp sometimes embeds it as data or plain text)
        phone_match = re.search(
            r"\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", card_text
        )
        phone = phone_match.group(0) if phone_match else ""

        # Address heuristic: look for a comma-separated pattern with a state code
        addr_match = re.search(
            r"\d+\s[\w\s]+(?:St|Ave|Blvd|Dr|Rd|Ln|Way|Court|Ct|Pl|Plaza)"
            r"[^,]*,\s*[\w\s]+,\s*[A-Z]{2}",
            card_text,
            re.I,
        )
        address = addr_match.group(0).strip() if addr_match else ""

        # External website link inside the card
        website = ""
        for a in card.find_all("a", href=True):
            h = a["href"]
            if h.startswith("http") and "yelp.com" not in h:
                website = h
                break

        businesses.append(
            {
                "name": name,
                "yelp_path": biz_slug,
                "rating": rating,
                "review_count": review_count,
                "address": address,
                "phone": phone,
                "website": website,
            }
        )
        if len(businesses) >= 25:
            break

    return businesses


def _scrape_yelp(category: str, city: str) -> list[dict]:
    url = _yelp_url(category, city)
    import requests
    try:
        resp = requests.get(url, headers=YELP_HEADERS, timeout=15)
        html = resp.text if resp.status_code == 200 else ""
    except Exception as exc:
        print(f"  [leads] Yelp fetch failed: {exc}")
        html = ""

    if not html:
        return []

    return _parse_yelp_html(html)


# ---------------------------------------------------------------------------
# Website quality check
# ---------------------------------------------------------------------------

def _check_website(url: str) -> dict:
    """Return a quality dict for a given website URL."""
    result = {
        "reachable": False,
        "mobile_friendly": False,
        "has_meta_description": False,
        "has_title": False,
        "quality_score": 0,   # 0-3; lower = worse
        "issues": [],
    }
    if not url:
        result["issues"].append("no website")
        return result

    html = fetch_page(url, timeout=10)
    if not html:
        result["issues"].append("site unreachable")
        return result

    result["reachable"] = True
    soup = BeautifulSoup(html, "html.parser")

    # Title tag
    title_tag = soup.find("title")
    if title_tag and title_tag.get_text(strip=True):
        result["has_title"] = True
        result["quality_score"] += 1
    else:
        result["issues"].append("missing <title>")

    # Meta description
    meta_desc = soup.find("meta", attrs={"name": re.compile("description", re.I)})
    if meta_desc and meta_desc.get("content", "").strip():
        result["has_meta_description"] = True
        result["quality_score"] += 1
    else:
        result["issues"].append("no meta description")

    # Viewport / mobile friendliness
    viewport = soup.find("meta", attrs={"name": re.compile("viewport", re.I)})
    if viewport:
        result["mobile_friendly"] = True
        result["quality_score"] += 1
    else:
        result["issues"].append("not mobile friendly (no viewport meta)")

    return result


# ---------------------------------------------------------------------------
# Lead scoring: qualify businesses for outreach
# ---------------------------------------------------------------------------

def _is_target(biz: dict, web_check: dict) -> bool:
    """Return True if this business is worth targeting."""
    # No website at all → always a target
    if not biz.get("website"):
        return True
    # Unreachable site
    if not web_check.get("reachable"):
        return True
    # Poor quality site (0 or 1 out of 3)
    if web_check.get("quality_score", 3) <= 1:
        return True
    return False


# ---------------------------------------------------------------------------
# Claude content generation
# ---------------------------------------------------------------------------

def _business_type_label(category: str) -> str:
    labels = {
        "restaurants": "restaurant",
        "plumbers": "plumbing business",
        "electricians": "electrical contractor",
        "hair salons": "hair salon",
        "cleaning services": "cleaning service",
        "landscaping": "landscaping company",
        "personal trainers": "personal training business",
        "photographers": "photography studio",
        "yoga studios": "yoga studio",
        "dentists": "dental practice",
    }
    return labels.get(category.lower(), "local business")


def _generate_outreach(biz: dict, category: str, web_issues: list[str]) -> dict:
    biz_name = biz["name"]
    biz_type = _business_type_label(category)
    city = biz.get("city", "")
    rating = biz.get("rating", "")
    reviews = biz.get("review_count", "0")
    has_website = bool(biz.get("website"))

    if has_website:
        website_context = (
            f"Their current website has these problems: {', '.join(web_issues)}."
        )
    else:
        website_context = "They currently have no website at all."

    prompt = f"""You are a freelance web designer reaching out to a local small business.

Business details:
- Name: {biz_name}
- Type: {biz_type}
- City: {city}
- Yelp rating: {rating} ({reviews} reviews)
- Website situation: {website_context}

Produce exactly this JSON (no extra keys, no markdown fences):
{{
  "subject": "<email subject line, max 10 words, specific to this business>",
  "email_body": "<cold email body, 120-150 words, personalised, professional, mentions {PRICE_RANGE} for a new mobile-friendly website, ends with a clear CTA>",
  "value_prop": "<one paragraph, 60-80 words, specific to why a {biz_type} needs a good website>",
  "follow_up": "<follow-up message for 3 days later, 60-80 words, friendly nudge referencing the first email>"
}}"""

    try:
        data = generate_json(prompt, smart=False, max_tokens=800)
        # Validate expected keys are present
        for key in ("subject", "email_body", "value_prop", "follow_up"):
            if key not in data:
                data[key] = ""
        return data
    except Exception as exc:
        print(f"  [leads] Claude generation failed for {biz_name}: {exc}")
        return {
            "subject": f"Quick question about {biz_name}'s website",
            "email_body": "",
            "value_prop": "",
            "follow_up": "",
        }


# ---------------------------------------------------------------------------
# File I/O helpers
# ---------------------------------------------------------------------------

def _save_leads_csv(path: Path, rows: list[dict]):
    fieldnames = [
        "name", "category", "city", "rating", "review_count",
        "address", "phone", "website", "reachable", "mobile_friendly",
        "has_title", "has_meta_description", "quality_score", "issues",
        "is_target",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _save_email(email_dir: Path, biz_name: str, content: dict):
    slug = slugify(biz_name)
    out_path = email_dir / f"{slug}.txt"
    text = (
        f"SUBJECT: {content.get('subject', '')}\n"
        f"{'=' * 60}\n\n"
        f"{content.get('email_body', '')}\n\n"
        f"{'—' * 60}\n"
        f"VALUE PROPOSITION\n"
        f"{'—' * 60}\n"
        f"{content.get('value_prop', '')}\n\n"
        f"{'—' * 60}\n"
        f"FOLLOW-UP (3 days later)\n"
        f"{'—' * 60}\n"
        f"{content.get('follow_up', '')}\n"
    )
    save_text(out_path, text)
    return out_path


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------

def run(config: Optional[dict] = None) -> dict:
    """
    Execute one lead-generation run.

    Parameters
    ----------
    config : dict, optional
        Accepts ``city`` and/or ``category`` override keys.

    Returns
    -------
    dict with keys: status, city, category, total_found, targets, outputs
    """
    config = config or {}

    # --- Resolve city / category ----------------------------------------
    state = _load_state()

    if "city" in config and "category" in config:
        city = config["city"]
        category = config["category"]
    elif "city" in config:
        city = config["city"]
        _, category = _next_city_category(state)
    elif "category" in config:
        category = config["category"]
        city, _ = _next_city_category(state)
    else:
        city, category = _next_city_category(state)

    print(f"[leads] Targeting: {category} in {city}")

    # --- Scrape Yelp --------------------------------------------------------
    businesses = _scrape_yelp(category, city)
    print(f"[leads] Found {len(businesses)} businesses on Yelp")

    # Attach city to each record for later use
    for b in businesses:
        b["city"] = city
        b["category"] = category

    # --- Website quality checks -------------------------------------------
    csv_rows = []
    targets = []

    for biz in businesses:
        web_check = {"quality_score": 0, "issues": [], "reachable": False,
                     "mobile_friendly": False, "has_title": False,
                     "has_meta_description": False}

        if biz.get("website"):
            print(f"  [leads] Checking website for {biz['name']} …")
            web_check = _check_website(biz["website"])
            time.sleep(0.5)  # polite delay

        is_tgt = _is_target(biz, web_check)

        row = {
            **biz,
            **web_check,
            "issues": "; ".join(web_check.get("issues", [])),
            "is_target": is_tgt,
        }
        csv_rows.append(row)
        if is_tgt:
            targets.append((biz, web_check.get("issues", [])))

    # --- Limit targets to MAX_TARGETS_PER_RUN ------------------------------
    targets = targets[:MAX_TARGETS_PER_RUN]
    print(f"[leads] {len(targets)} businesses qualify for outreach")

    # --- Prepare output directories ----------------------------------------
    run_dir = today_dir(OUTPUTS_BASE)
    email_dir = run_dir / "emails"
    email_dir.mkdir(parents=True, exist_ok=True)

    # --- Save CSV -----------------------------------------------------------
    csv_path = run_dir / "leads.csv"
    _save_leads_csv(csv_path, csv_rows)

    # --- Generate and save email content ------------------------------------
    output_files = [str(csv_path)]
    email_count = 0

    for biz, issues in targets:
        print(f"  [leads] Generating email for {biz['name']} …")
        content = _generate_outreach(biz, category, issues)
        email_path = _save_email(email_dir, biz["name"], content)
        output_files.append(str(email_path))
        email_count += 1
        time.sleep(0.3)

    # --- Summary ------------------------------------------------------------
    summary_lines = [
        f"Local Lead Generation Run",
        f"=========================",
        f"Date      : {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"City      : {city}",
        f"Category  : {category}",
        f"",
        f"Businesses found on Yelp : {len(businesses)}",
        f"Targets identified       : {len(targets)}",
        f"Emails generated         : {email_count}",
        f"",
        f"Targeting criteria:",
        f"  - No website present",
        f"  - Website unreachable",
        f"  - Website quality score ≤ 1/3 (missing mobile, title, or meta desc)",
        f"",
        f"Output files:",
        f"  {csv_path}",
        f"  {email_dir}/  ({email_count} email files)",
    ]
    summary_text = "\n".join(summary_lines)
    summary_path = run_dir / "summary.txt"
    save_text(summary_path, summary_text)
    output_files.append(str(summary_path))

    # --- Log to shared tracker ---------------------------------------------
    log_output(
        agent_name="local_leads",
        title=f"Local leads: {category} in {city}",
        path=str(run_dir),
        notes=f"{len(businesses)} found, {len(targets)} targeted",
    )

    # --- Persist rotation state --------------------------------------------
    state["runs"].append({
        "city": city,
        "category": category,
        "targets": len(targets),
        "timestamp": __import__("datetime").datetime.now().isoformat(),
    })
    _save_state(state)

    print(f"[leads] Done. Outputs in {run_dir}")
    print(summary_text)

    return {
        "status": "success",
        "city": city,
        "category": category,
        "total_found": len(businesses),
        "targets": len(targets),
        "outputs": output_files,
    }


if __name__ == "__main__":
    result = run()
    sys.exit(0 if result["status"] == "success" else 1)
