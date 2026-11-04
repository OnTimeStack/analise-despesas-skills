#!/usr/bin/env python3
"""Compatibility wrapper around the shared strategic-analysis core."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from expense_skills.analysis import ExpenseAnalyzer
from expense_skills.categorization import Categorizer
from expense_skills.cli import analyze_main

__all__ = ["Categorizer", "ExpenseAnalyzer"]


if __name__ == "__main__":
    raise SystemExit(analyze_main())
