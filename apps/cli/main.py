from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli._bootstrap import ensure_repo_paths

ensure_repo_paths()

from apps.cli.commands import scan, stream


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fluke Community CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan.register(subparsers)
    stream.register(subparsers)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
