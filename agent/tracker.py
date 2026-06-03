"""
Tracks published products, daily runs, and sales performance.
All data stored in data/products.json — committed to git for persistence.
"""

import json
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional


DATA_DIR = Path(__file__).parent.parent / "data"
PRODUCTS_FILE = DATA_DIR / "products.json"
STATS_FILE = DATA_DIR / "stats.json"


def _load(path: Path) -> dict | list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {} if path == STATS_FILE else []


def _save(path: Path, data):
    DATA_DIR.mkdir(exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def get_all_products() -> List[Dict]:
    return _load(PRODUCTS_FILE)


def get_recently_used_niches(days: int = 3) -> List[str]:
    """Return niches used in the last N days to avoid repetition."""
    products = get_all_products()
    cutoff = datetime.now()
    recent = []
    for p in products:
        created = p.get("created_at", "")
        if created:
            try:
                age = (cutoff - datetime.fromisoformat(created)).days
                if age < days:
                    recent.append(p["niche"])
            except Exception:
                pass
    return list(set(recent))


def record_product(product: Dict, pdf_path: Path, gumroad_url: Optional[str]) -> Dict:
    """Save a newly published product to the tracker."""
    products = get_all_products()

    entry = {
        "id": len(products) + 1,
        "title": product["title"],
        "niche": product["niche"],
        "price_cents": product.get("price_cents", 1200),
        "gumroad_url": gumroad_url,
        "pdf_file": str(pdf_path.name),
        "created_at": datetime.now().isoformat(),
        "sales": 0,
        "revenue_cents": 0,
        "tweet": product.get("tweet", ""),
        "reddit_post": product.get("reddit_post", ""),
    }

    products.append(entry)
    _save(PRODUCTS_FILE, products)
    return entry


def update_sales(gumroad_sales_data: Dict):
    """Update sales counts from Gumroad API data (call periodically)."""
    products = get_all_products()
    stats = _load(STATS_FILE)

    total_revenue = gumroad_sales_data.get("revenue_cents", 0)
    total_sales = gumroad_sales_data.get("total", 0)

    stats["last_updated"] = datetime.now().isoformat()
    stats["total_sales"] = total_sales
    stats["total_revenue_cents"] = total_revenue
    stats["total_revenue_dollars"] = round(total_revenue / 100, 2)
    stats["products_published"] = len(products)
    stats["monthly_goal_cents"] = 100000  # $1000
    stats["progress_pct"] = round((total_revenue / 100000) * 100, 1)

    _save(STATS_FILE, stats)
    return stats


def print_dashboard():
    """Print a quick revenue dashboard to stdout."""
    products = get_all_products()
    stats = _load(STATS_FILE)

    print("\n" + "=" * 52)
    print("  REVENUE DASHBOARD")
    print("=" * 52)
    print(f"  Products published : {len(products)}")
    print(f"  Total sales        : {stats.get('total_sales', 0)}")
    print(f"  Total revenue      : ${stats.get('total_revenue_dollars', 0):.2f}")
    progress = stats.get('progress_pct', 0)
    bar = "█" * int(progress / 5) + "░" * (20 - int(progress / 5))
    print(f"  $1000 goal         : [{bar}] {progress}%")
    print("=" * 52)

    if products:
        print("\n  Recent products:")
        for p in products[-5:]:
            price = p['price_cents'] / 100
            print(f"  • {p['title'][:42]:<42} ${price:.0f}")
    print()
