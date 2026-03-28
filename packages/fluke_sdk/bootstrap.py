from __future__ import annotations

import sys
from pathlib import Path


def ensure_repo_paths() -> None:
    root = Path(__file__).resolve().parents[2]
    packages = root / "packages"
    for path in (root, packages):
        text = str(path)
        if text in sys.path:
            sys.path.remove(text)
    sys.path.insert(0, str(root))
    sys.path.insert(0, str(packages))
