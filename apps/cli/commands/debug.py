from __future__ import annotations

import argparse

from apps.cli.runtime import build_workflows, load_extensions
from fluke_app import export_debug_bundle
from fluke_plugins import build_profile_registry


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("debug", help="Export diagnostics for bug reports and contributor triage")
    debug_subparsers = parser.add_subparsers(dest="debug_command", required=True)

    bundle_parser = debug_subparsers.add_parser("bundle", help="Export a debug bundle zip")
    bundle_parser.add_argument("--output", required=True, help="Zip path to create")
    bundle_parser.add_argument("--database", default="data/fluke.db", help="Optional SQLite database to summarize")
    bundle_parser.set_defaults(func=handle_bundle)


async def handle_bundle(args: argparse.Namespace) -> int:
    plugin_bundle = load_extensions()
    workflow_catalog = build_workflows()
    profile_registry = build_profile_registry()
    output = export_debug_bundle(
        args.output,
        profile_registry=profile_registry,
        workflow_catalog=workflow_catalog,
        plugin_bundle=plugin_bundle,
        database_path=args.database,
    )
    print(output)
    return 0
