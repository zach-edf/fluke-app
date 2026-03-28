from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    packages = root / "packages"
    for path in (root, packages):
        text = str(path)
        if text not in sys.path:
            sys.path.insert(0, text)
