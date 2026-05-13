#!/usr/bin/env python3
"""Validate the public minimal stack example against the campaign schema."""
import json
from pathlib import Path

import jsonschema

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "campaign.schema.json"
EXAMPLE_PATH = REPO_ROOT / "examples" / "minimal-stack" / "minimal_stack_template.json"


def main() -> int:
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema = json.load(f)
    with open(EXAMPLE_PATH, encoding="utf-8") as f:
        data = json.load(f)

    jsonschema.validate(data, schema)
    print("minimal example valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
