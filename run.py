#!/usr/bin/env python3
"""
Entry point for running the agent locally or via GitHub Actions.

Usage:
  python run.py              # Create 1 product and publish to Gumroad
  python run.py --dry-run    # Generate locally, skip Gumroad
  python run.py --count 2    # Create 2 products
  python run.py --sales      # Check current sales only
"""

import sys
from agent.main import run, check_sales


def main():
    args = sys.argv[1:]

    if "--sales" in args:
        check_sales()
        return

    dry_run = "--dry-run" in args

    count = 1
    if "--count" in args:
        idx = args.index("--count")
        try:
            count = int(args[idx + 1])
        except (IndexError, ValueError):
            count = 1

    count = max(1, min(count, 5))  # Cap at 5 per run to control API costs

    run(dry_run=dry_run, products_count=count)


if __name__ == "__main__":
    main()
