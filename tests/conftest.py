"""Pytest configuration.

Makes sure the project root is importable so that ``import lostpart`` works
when the tests are run from a checkout without installing the package.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
