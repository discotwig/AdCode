#!/usr/bin/env python3
"""Scaffold a new AdCode customer directory.

Usage:
    python scripts/new_customer.py <slug> <account_id>

Example:
    python scripts/new_customer.py acme-marketing act_123456789
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a new per-customer directory under customers/."
    )
    parser.add_argument("slug", help="Customer slug, lowercase with hyphens (e.g. acme-marketing)")
    parser.add_argument("account_id", help="Facebook ad account ID (e.g. act_123456789)")
    args = parser.parse_args()

    customer_dir = REPO_ROOT / "customers" / args.slug

    if customer_dir.exists():
        print(f"Error: {customer_dir} already exists.", file=sys.stderr)
        return 1

    (customer_dir / "campaigns").mkdir(parents=True)
    (customer_dir / "state").mkdir(parents=True)
    (customer_dir / "campaigns" / ".gitkeep").touch()
    (customer_dir / "state" / ".gitkeep").touch()

    config = {
        "customer_slug": args.slug,
        "account_id": args.account_id,
        "campaigns_dir": "campaigns",
        "state_dir": "state",
    }
    (customer_dir / "config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    shutil.copy(REPO_ROOT / ".env.example", customer_dir / ".env.example")

    print(f"Created customers/{args.slug}/")
    print()
    print("Next steps:")
    print(f"  1. cp customers/{args.slug}/.env.example customers/{args.slug}/.env")
    print(f"  2. Fill in FB_APP_ID, FB_APP_SECRET, FB_ACCESS_TOKEN, ANTHROPIC_API_KEY")
    print(f"  3. python src/mcp_server.py --config customers/{args.slug}/config.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
