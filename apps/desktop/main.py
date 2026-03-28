from __future__ import annotations

import sys

from apps.desktop.bootstrap import ensure_repo_paths

ensure_repo_paths()

from apps.desktop.app import run


def main() -> int:
    try:
        return run()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
