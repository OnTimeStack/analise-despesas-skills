#!/usr/bin/env python3
"""ChatGPT/Codex wrapper for the repository's shared core."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
SOURCE_ROOT = PLUGIN_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from expense_skills.cli import consolidate_main

if __name__ == "__main__":
    raise SystemExit(consolidate_main())
