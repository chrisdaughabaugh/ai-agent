"""
Publishes digital products to Gumroad via their REST API.
Docs: https://app.gumroad.com/api
"""

import os
import requests
from pathlib import Path
from typing import Dict, Optional


GUMROAD_BASE = "https://api.gumroad.com/v2"


def _token() -> str:
    token = os.environ.get("GUMROAD_ACCESS_TOKEN", "")
    if not token:
        raise EnvironmentError("GUMROAD_ACCESS_TOKEN not set")
    return token


def create_product(product: Dict) -> Dict:
    """
    Create a new product on Gumroad and return the API response data.
    The product starts as unpublished so we can attach the file before going live.
    """
    price_cents = product.get("price_cents", 1200)

    payload = {
        "access_token": _token(),
        "name": product["title"],
        "description": product["description"],
        "price": price_cents,
        "published": "false",
        "tags": f"{product.get('niche', '')},{product.get('primary_keyword', '')}",
    }

    resp = requests.post(f"{GUMROAD_BASE}/products", data=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    if not data.get("success"):
        raise RuntimeError(f"Gumroad create_product failed: {data.get('message')}")

    return data["product"]


def upload_file(product_id: str, file_path: Path) -> bool:
    """Attach the PDF file to an existing Gumroad product."""
    with open(file_path, "rb") as f:
        resp = requests.put(
            f"{GUMROAD_BASE}/products/{product_id}",
            data={"access_token": _token()},
            files={"file": (file_path.name, f, "application/pdf")},
            timeout=60,
        )
    resp.raise_for_status()
    data = resp.json()
    return data.get("success", False)


def publish_product(product_id: str) -> bool:
    """Make the product live (visible and purchasable)."""
    resp = requests.put(
        f"{GUMROAD_BASE}/products/{product_id}/enable",
        data={"access_token": _token()},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("success", False)


def get_sales_summary() -> Dict:
    """Return total sales count and revenue across all products."""
    resp = requests.get(
        f"{GUMROAD_BASE}/sales",
        params={"access_token": _token()},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if not data.get("success"):
        return {"sales": [], "total": 0, "revenue_cents": 0}

    sales = data.get("sales", [])
    revenue = sum(int(s.get("price", 0)) for s in sales)

    return {
        "sales": sales,
        "total": len(sales),
        "revenue_cents": revenue,
        "revenue_dollars": revenue / 100,
    }


def get_all_products() -> list:
    """List all products on the account."""
    resp = requests.get(
        f"{GUMROAD_BASE}/products",
        params={"access_token": _token()},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("products", []) if data.get("success") else []


def publish_to_gumroad(product: Dict, pdf_path: Path) -> Optional[str]:
    """
    Full publish flow: create product → upload PDF → go live.
    Returns the Gumroad product URL or None on failure.
    """
    print(f"  → Creating Gumroad listing for: {product['title']}")
    gum_product = create_product(product)
    product_id = gum_product["id"]

    print(f"  → Uploading PDF ({pdf_path.stat().st_size // 1024} KB)...")
    upload_file(product_id, pdf_path)

    print(f"  → Publishing product...")
    publish_product(product_id)

    url = gum_product.get("short_url") or gum_product.get("url", "")
    print(f"  ✓ Live at: {url}")
    return url
