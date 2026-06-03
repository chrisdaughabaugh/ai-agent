"""
Discovers and selects the best digital product niche for today's run.
Uses curated niche data + Reddit trending topics (no API key needed).
"""

import json
import random
import requests
from pathlib import Path
from typing import Dict, List, Optional


NICHES_PATH = Path(__file__).parent.parent / "templates" / "niches.json"


def load_niches() -> List[Dict]:
    with open(NICHES_PATH) as f:
        return json.load(f)


def get_trending_reddit_titles(subreddit: str) -> List[str]:
    """Fetch hot post titles from a subreddit (no auth required)."""
    try:
        url = f"https://www.reddit.com/r/{subreddit}/hot.json?limit=15"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; research-agent/1.0)"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            posts = resp.json()["data"]["children"]
            return [p["data"]["title"] for p in posts]
    except Exception:
        pass
    return []


def select_niche(recently_used: Optional[List[str]] = None) -> Dict:
    """
    Pick the best niche to target today.
    Weights toward low-competition niches and avoids recent repeats.
    """
    niches = load_niches()
    recently_used = recently_used or []

    available = [n for n in niches if n["niche"] not in recently_used]
    if not available:
        available = niches

    competition_weight = {"low": 4, "medium": 2, "high": 1}
    weights = [competition_weight.get(n["competition"], 1) for n in available]

    chosen = random.choices(available, weights=weights, k=1)[0]

    # Enrich with trending Reddit context
    trending = get_trending_reddit_titles("sidehustle")
    trending += get_trending_reddit_titles("personalfinance")
    if trending:
        chosen["trending_context"] = trending[:8]

    return chosen


def pick_product_idea(niche: Dict) -> Dict:
    """Select a specific product concept from the niche."""
    topic = random.choice(niche["topics"])
    pain_point = random.choice(niche["pain_points"])
    keyword = random.choice(niche["keywords"])

    return {
        "niche": niche["niche"],
        "title": topic,
        "audience": niche["audience"],
        "pain_point": pain_point,
        "primary_keyword": keyword,
        "suggested_price": niche["avg_price"],
        "trending_context": niche.get("trending_context", []),
    }
