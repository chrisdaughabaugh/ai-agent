"""
Printify API client — uploads designs and creates print-on-demand products
that auto-publish to the connected Shopify store.

Docs: https://developers.printify.com/
"""

import os
import base64
import requests
from pathlib import Path
from typing import Dict, List, Optional

BASE = "https://api.printify.com/v1"

# Popular product blueprints — t-shirts, mugs, totes
# These IDs are stable in Printify's catalog
TARGET_BLUEPRINTS = {
    "Unisex T-Shirt":  {"id": 6,   "markup": 2.8},  # Gildan 64000 — most popular
    "Classic Mug":     {"id": 19,  "markup": 2.5},  # 11oz ceramic
    "Tote Bag":        {"id": 77,  "markup": 2.4},  # Canvas tote
}

# Colors to include per product (keeps variant count manageable)
SHIRT_COLORS  = ["Black", "White", "Navy", "Forest Green", "Heather Gray"]
MUG_COLORS    = ["White"]
TOTE_COLORS   = ["Natural"]
SHIRT_SIZES   = ["S", "M", "L", "XL", "2XL"]


def _headers() -> Dict:
    token = os.environ.get("PRINTIFY_API_KEY", "")
    if not token:
        raise EnvironmentError("PRINTIFY_API_KEY not set")
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_shop_id() -> str:
    """Return the first connected shop's ID."""
    r = requests.get(f"{BASE}/shops.json", headers=_headers(), timeout=15)
    r.raise_for_status()
    shops = r.json()
    if not shops:
        raise RuntimeError("No shops connected to this Printify account. Connect Shopify first.")
    return str(shops[0]["id"])


def upload_image(image_path: Path) -> str:
    """Upload a PNG/JPG to Printify and return the image ID."""
    with open(image_path, "rb") as f:
        data = base64.b64encode(f.read()).decode()

    payload = {
        "file_name": image_path.name,
        "contents":  data,
    }
    r = requests.post(f"{BASE}/uploads/images.json", json=payload,
                      headers=_headers(), timeout=60)
    r.raise_for_status()
    return r.json()["id"]


def get_print_providers(blueprint_id: int) -> List[Dict]:
    """Get available print providers for a blueprint, sorted by rating."""
    r = requests.get(
        f"{BASE}/catalog/blueprints/{blueprint_id}/print_providers.json",
        headers=_headers(), timeout=15
    )
    r.raise_for_status()
    return r.json()


def get_variants(blueprint_id: int, provider_id: int,
                 color_filter: List[str], size_filter: List[str]) -> List[Dict]:
    """Return variants matching the desired colors and sizes."""
    r = requests.get(
        f"{BASE}/catalog/blueprints/{blueprint_id}/print_providers/{provider_id}/variants.json",
        headers=_headers(), timeout=15
    )
    r.raise_for_status()
    all_variants = r.json().get("variants", [])

    chosen = []
    for v in all_variants:
        if not v.get("is_available", True):
            continue
        title = v.get("title", "")
        # title is usually "Color / Size" or just the option
        color_ok = not color_filter or any(c.lower() in title.lower() for c in color_filter)
        size_ok  = not size_filter  or any(s == title.split("/")[-1].strip() for s in size_filter)
        if color_ok and size_ok:
            chosen.append(v)

    return chosen[:30]  # cap to avoid massive variant lists


def create_product(shop_id: str, blueprint_id: int, provider_id: int,
                   variants: List[Dict], image_id: str,
                   title: str, description: str, tags: List[str],
                   markup: float) -> Dict:
    """Create a product on Printify with the uploaded design."""

    # Build variant list with pricing
    variant_list = []
    for v in variants:
        cost = v.get("cost", 800)  # cost in cents
        price = round((cost / 100) * markup, 2)
        variant_list.append({
            "id":      v["id"],
            "price":   int(price * 100),
            "is_enabled": True,
        })

    # Print area — use the first available print area (usually "front")
    payload = {
        "title":        title,
        "description":  description,
        "blueprint_id": blueprint_id,
        "print_provider_id": provider_id,
        "variants":     variant_list,
        "print_areas": [
            {
                "variant_ids": [v["id"] for v in variants],
                "placeholders": [
                    {
                        "position": "front",
                        "images": [
                            {
                                "id":       image_id,
                                "x":        0.5,
                                "y":        0.5,
                                "scale":    1.0,
                                "angle":    0,
                            }
                        ],
                    }
                ],
            }
        ],
        "tags": tags[:13],  # Printify allows up to 13 tags
    }

    r = requests.post(
        f"{BASE}/shops/{shop_id}/products.json",
        json=payload, headers=_headers(), timeout=30
    )
    r.raise_for_status()
    return r.json()


def publish_product(shop_id: str, product_id: str) -> bool:
    """Push the product live to the connected Shopify store."""
    payload = {
        "title":        True,
        "description":  True,
        "images":       True,
        "variants":     True,
        "tags":         True,
        "keyFeatures":  True,
        "shipping_template": True,
    }
    r = requests.post(
        f"{BASE}/shops/{shop_id}/products/{product_id}/publish.json",
        json=payload, headers=_headers(), timeout=30
    )
    r.raise_for_status()
    return True


def publish_design_to_shopify(design: Dict, image_path: Path) -> List[Dict]:
    """
    Full pipeline: take a design dict + PNG path → publish products to Shopify.
    Returns list of created product details.
    """
    print(f"  [Printify] Starting publish for: {design['title']}")

    shop_id = get_shop_id()
    print(f"  [Printify] Shop ID: {shop_id}")

    print(f"  [Printify] Uploading image...")
    image_id = upload_image(image_path)

    created = []

    for product_name, bp_info in TARGET_BLUEPRINTS.items():
        blueprint_id = bp_info["id"]
        markup       = bp_info["markup"]

        print(f"  [Printify] Creating {product_name}...")

        try:
            providers = get_print_providers(blueprint_id)
            if not providers:
                continue
            # Pick first available provider
            provider = providers[0]
            provider_id = provider["id"]

            # Pick colors/sizes per product type
            if "T-Shirt" in product_name:
                colors, sizes = SHIRT_COLORS, SHIRT_SIZES
            elif "Mug" in product_name:
                colors, sizes = MUG_COLORS, []
            else:
                colors, sizes = TOTE_COLORS, []

            variants = get_variants(blueprint_id, provider_id, colors, sizes)
            if not variants:
                print(f"  [Printify] No variants found for {product_name}, skipping")
                continue

            title = f"{design['title']} — {product_name}"
            description = (
                f"<p>{design.get('listing_description', design['title'])}</p>"
                f"<p>Original artwork printed on demand. Ships in 3-5 business days.</p>"
            )
            tags = design.get("tags", [])[:13]

            product = create_product(
                shop_id, blueprint_id, provider_id,
                variants, image_id, title, description, tags, markup
            )

            product_id = product["id"]
            publish_product(shop_id, product_id)

            url = f"https://your-store.myshopify.com/products/{product.get('handle', product_id)}"
            print(f"  [Printify] ✓ {product_name} live: {product_id}")

            created.append({
                "product_type": product_name,
                "printify_id":  product_id,
                "title":        title,
            })

        except Exception as e:
            print(f"  [Printify] Error on {product_name}: {e}")
            continue

    return created
