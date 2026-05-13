#!/usr/bin/env python3
"""Scaffold a new AdCode customer directory with an initial stack.

Usage:
    python scripts/new_customer.py <slug> <account_id> [<stack_name>]

Examples:
    python scripts/new_customer.py acme-marketing act_123456789
    python scripts/new_customer.py acme-marketing act_123456789 q2_brand
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create a new per-customer directory with an initial Ad Stack under customers/."
    )
    parser.add_argument("slug", help="Customer slug, lowercase with hyphens (e.g. acme-marketing)")
    parser.add_argument("account_id", help="Facebook ad account ID (e.g. act_123456789)")
    parser.add_argument(
        "stack_name",
        nargs="?",
        help="Stack folder name (default: <slug>_v1)",
    )
    args = parser.parse_args()

    customer_dir = REPO_ROOT / "customers" / args.slug
    stack_name = args.stack_name or f"{args.slug}_v1"
    stack_dir = customer_dir / stack_name

    if customer_dir.exists():
        print(f"Error: {customer_dir} already exists.", file=sys.stderr)
        return 1

    stack_dir.mkdir(parents=True)

    # .env.example in the stack directory — operator copies and fills in credentials
    shutil.copy(REPO_ROOT / ".env.example", stack_dir / ".env.example")

    # Blank stack template stub
    template_name = f"{stack_name}_template.json"
    template = {
        "account_id": args.account_id,
        "campaigns": [],
    }
    (stack_dir / template_name).write_text(
        json.dumps(template, indent=2) + "\n", encoding="utf-8"
    )

    print(f"Created customers/{args.slug}/{stack_name}/")
    print()
    print("Next steps:")
    print(f"  1. cp customers/{args.slug}/{stack_name}/.env.example customers/{args.slug}/{stack_name}/.env")
    print(f"  2. Fill in FB_APP_ID, FB_APP_SECRET, FB_ACCESS_TOKEN, ANTHROPIC_API_KEY in that .env")
    print(f"  3. Edit customers/{args.slug}/{stack_name}/{template_name} to define your campaigns")
    print(f"  4. python src/mcp_server.py --config customers/{args.slug}/{stack_name}/{template_name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
