#!/usr/bin/env python3
"""Legacy-compatible adapter for the shared merchant-review service."""

import sys
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    if (parent / "src" / "expense_skills").is_dir():
        sys.path.insert(0, str(parent / "src"))
        break

from expense_skills.cli import merchant_review_main

if __name__ == "__main__":
    raise SystemExit(merchant_review_main())
