#!/usr/bin/env python3
"""Portable adapter for the unified expense-processing workflow."""

import sys
from pathlib import Path

for parent in Path(__file__).resolve().parents:
    if (parent / "src" / "expense_skills").is_dir():
        sys.path.insert(0, str(parent / "src"))
        break

from expense_skills.cli import process_expenses_main

if __name__ == "__main__":
    raise SystemExit(process_expenses_main())
