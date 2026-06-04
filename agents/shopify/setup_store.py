"""
One-time Shopify store setup for RISE SUPPLY CO.
Run this once after connecting Shopify to Printify.

Sets up: collections, homepage SEO meta, navigation structure.
Requires: SHOPIFY_STORE_URL and SHOPIFY_API_TOKEN env vars.
"""

import os
import sys
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from brand.config import BRAND

STORE   = os.environ.get("SHOPIFY_STORE_URL", "").rstrip("/")  # e.g. mystore.myshopify.com
TOKEN   = os.environ.get("SHOPIFY_API_TOKEN", "")
VERSION = "2024-01"
BASE    = f"https://{STORE}/admin/api/{VERSION}"


def headers():
    return {
        "X-Shopify-Access-Token": TOKEN,
        "Content-Type": "application/json",
    }


def create_collection(title: str, description: str, sort_order: str = "best-selling") -> dict:
    payload = {
        "custom_collection": {
            "title":        title,
            "body_html":    f"<p>{description}</p>",
            "sort_order":   sort_order.lower().replace("_", "-"),
            "published":    True,
        }
    }
    r = requests.post(f"{BASE}/custom_collections.json", json=payload, headers=headers(), timeout=15)
    r.raise_for_status()
    col = r.json()["custom_collection"]
    print(f"  Created collection: {title} (id={col['id']})")
    return col


def update_shop_meta():
    """Set store name and metafields for SEO."""
    seo = BRAND["shopify"]["seo"]
    payload = {
        "shop": {
            "name":              BRAND["name"],
            "meta_title":        seo["title"],
            "meta_description":  seo["description"],
        }
    }
    r = requests.put(f"{BASE}/shop.json", json=payload, headers=headers(), timeout=15)
    if r.status_code in (200, 201):
        print("  Updated shop name and SEO meta.")
    else:
        print(f"  Shop meta update: {r.status_code} — {r.text[:200]}")


def run():
    if not STORE or not TOKEN:
        print("ERROR: Set SHOPIFY_STORE_URL and SHOPIFY_API_TOKEN env vars.")
        print("  SHOPIFY_STORE_URL = yourstore.myshopify.com")
        print("  SHOPIFY_API_TOKEN = your Admin API token (Settings > Apps > private apps)")
        sys.exit(1)

    print(f"\n[Shopify Setup] Setting up store for {BRAND['name']}...")
    print(f"  Store: {STORE}\n")

    # Collections
    for col in BRAND["shopify"]["collections"]:
        try:
            create_collection(col["title"], col["description"], col["sort_order"])
        except Exception as e:
            print(f"  [WARN] Collection '{col['title']}' failed: {e}")

    # SEO / shop meta
    try:
        update_shop_meta()
    except Exception as e:
        print(f"  [WARN] Shop meta update failed: {e}")

    print(f"\n[Shopify Setup] Done! Visit your store admin to review.")
    print("  Next: connect Printify to Shopify in your Printify account settings.")


if __name__ == "__main__":
    run()
