"""Pytest bootstrap.

Ensures the in-tree ``packages/`` and repo root take import precedence over any
globally installed ``fluke-community`` editable build (which may point at a
different checkout). This mirrors ``apps.cli._bootstrap.ensure_repo_paths`` so
the test suite always exercises the code in this working tree.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
for _path in (_ROOT / "packages", _ROOT):
    _text = str(_path)
    if _text in sys.path:
        sys.path.remove(_text)
    sys.path.insert(0, _text)
