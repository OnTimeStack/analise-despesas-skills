#!/usr/bin/env python3
"""Compatibility wrapper around the shared consolidation core."""

from __future__ import annotations

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from expense_skills.cli import consolidate_main
from expense_skills.consolidation import ExpectedTotals, InvoiceConsolidator

__all__ = ["ExpectedTotals", "InvoiceConsolidator"]


if __name__ == "__main__":
    raise SystemExit(consolidate_main())
