"""
Main orchestrator — runs the full product creation and publishing pipeline.
Called daily by GitHub Actions or manually via: python run.py
"""

import os
import sys
import json
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

from agent.research import select_niche, pick_product_idea
from agent.content_generator import generate_product
from agent.pdf_builder import build_pdf
from agent.gumroad_publisher import publish_to_gumroad, get_sales_summary
from agent.tracker import (
    get_recently_used_niches,
    record_product,
    update_sales,
    print_dashboard,
)


def run(dry_run: bool = False, products_count: int = 1):
    """
    Full pipeline run.
    dry_run=True generates the product and PDF but skips Gumroad publishing.
    """
    load_dotenv()

    print(f"\n{'='*52}")
    print(f"  AI PRODUCT AGENT  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*52}\n")

    if dry_run:
        print("  [DRY RUN MODE — Gumroad publish skipped]\n")

    results = []

    for run_num in range(1, products_count + 1):
        print(f"  Run {run_num}/{products_count}")
        print(f"  {'─'*46}")

        # 1. Research
        print("  [1/5] Researching niches...")
        recently_used = get_recently_used_niches(days=3)
        niche = select_niche(recently_used=recently_used)
        idea = pick_product_idea(niche)
        print(f"        Niche: {idea['niche']} → {idea['title']}")

        # 2. Generate content
        print("  [2/5] Generating product content (Claude Haiku)...")
        product = generate_product(idea)
        print(f"        Title: {product['title']}")
        print(f"        Price: ${product['price_cents']/100:.2f}")

        # 3. Build PDF
        print("  [3/5] Building PDF...")
        pdf_path = build_pdf(product)
        size_kb = pdf_path.stat().st_size // 1024
        print(f"        Saved: {pdf_path.name} ({size_kb} KB)")

        # 4. Publish to Gumroad
        gumroad_url = None
        if not dry_run:
            print("  [4/5] Publishing to Gumroad...")
            try:
                gumroad_url = publish_to_gumroad(product, pdf_path)
            except Exception as e:
                print(f"        ERROR publishing: {e}")
                print("        Product saved locally. Check GUMROAD_ACCESS_TOKEN.")
        else:
            print("  [4/5] Skipping Gumroad (dry run)")

        # 5. Track + save marketing assets
        print("  [5/5] Saving to tracker...")
        entry = record_product(product, pdf_path, gumroad_url)

        # Write marketing assets to file
        marketing_path = pdf_path.with_suffix(".marketing.txt")
        with open(marketing_path, "w") as f:
            f.write(f"PRODUCT: {product['title']}\n")
            f.write(f"URL: {gumroad_url or 'Not published yet'}\n")
            f.write(f"PRICE: ${product['price_cents']/100:.2f}\n\n")
            f.write("── GUMROAD DESCRIPTION ──\n")
            f.write(product["description"] + "\n\n")
            f.write("── TWEET ──\n")
            f.write(product.get("tweet", "") + "\n\n")
            f.write("── REDDIT POST ──\n")
            f.write(product.get("reddit_post", "") + "\n")

        print(f"        Marketing copy: {marketing_path.name}")

        results.append({
            "title": product["title"],
            "gumroad_url": gumroad_url,
            "pdf": str(pdf_path),
            "price": product["price_cents"] / 100,
        })

        print()

    # Update sales stats from Gumroad
    if not dry_run:
        try:
            print("  Syncing sales data from Gumroad...")
            sales_data = get_sales_summary()
            stats = update_sales(sales_data)
        except Exception as e:
            print(f"  Warning: Could not sync sales: {e}")

    print_dashboard()

    print("  Today's products:")
    for r in results:
        status = r["gumroad_url"] or "local only"
        print(f"  • {r['title'][:45]:<45} ${r['price']:.0f}  {status}")

    print()
    return results


def check_sales():
    """Fetch and display current sales without creating new products."""
    load_dotenv()
    try:
        sales_data = get_sales_summary()
        stats = update_sales(sales_data)
        print_dashboard()
    except Exception as e:
        print(f"Error fetching sales: {e}")
