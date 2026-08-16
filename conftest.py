"""Puts the repo root on sys.path so `import config` and `import ledgerlens` work
without an editable install."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
