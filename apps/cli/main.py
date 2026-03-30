from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import traceback

from apps.cli._bootstrap import ensure_repo_paths

ensure_repo_paths()

from apps.cli import __version__
from apps.cli.commands import alert, debug, devices, fixtures, log, plugins, scan, sessions, stream, watch, workflow
from apps.cli.runtime import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fluke",
        description="Fluke Community CLI - connect, stream, and log readings from Fluke BLE meters.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging")
    parser.add_argument("--json", action="store_true", dest="json", help="Output in JSON format where supported")

    subparsers = parser.add_subparsers(dest="command", required=True)
    alert.register(subparsers)
    debug.register(subparsers)
    devices.register(subparsers)
    fixtures.register(subparsers)
    log.register(subparsers)
    plugins.register(subparsers)
    scan.register(subparsers)
    sessions.register(subparsers)
    stream.register(subparsers)
    watch.register(subparsers)
    workflow.register(subparsers)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    configure_logging(verbose=args.verbose)

    try:
        return asyncio.run(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        if args.verbose:
            traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
