"""Validate docs/req/requirements.yaml against docs/req/req-schema.json.

Exits 0 when the document is valid, 1 otherwise (so CI blocks the merge). Prints
every validation error, not just the first, to make a failing gate actionable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml
from jsonschema import Draft7Validator

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "req" / "requirements.yaml"
SCHEMA = ROOT / "docs" / "req" / "req-schema.json"


def main() -> int:
    if not DOC.is_file():
        print(f"error: requirements document not found: {DOC}", file=sys.stderr)
        return 1
    if not SCHEMA.is_file():
        print(f"error: schema not found: {SCHEMA}", file=sys.stderr)
        return 1

    try:
        document = yaml.safe_load(DOC.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"error: {DOC} is not valid YAML:\n{exc}", file=sys.stderr)
        return 1

    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    validator = Draft7Validator(schema)
    errors = sorted(validator.iter_errors(document), key=lambda e: list(e.absolute_path))

    if errors:
        print(f"FAIL: {DOC.name} does not match {SCHEMA.name} ({len(errors)} error(s)):")
        for err in errors:
            location = "$" + "".join(f"[{p!r}]" for p in err.absolute_path)
            print(f"  - {location}: {err.message}")
        return 1

    count = len(document.get("requirements", []))
    print(f"OK: {DOC.name} is valid against {SCHEMA.name} ({count} requirement(s)).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
