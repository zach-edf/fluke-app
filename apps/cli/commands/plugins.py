from __future__ import annotations

import argparse

from apps.cli.formatters import format_plugin, output_list, plugin_to_dict
from apps.cli.runtime import load_extensions


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("plugins", help="Inspect loaded profile and workflow plugins")
    plugin_subparsers = parser.add_subparsers(dest="plugins_command", required=True)

    list_parser = plugin_subparsers.add_parser("list", help="List discovered plugins")
    list_parser.set_defaults(func=handle_list)


async def handle_list(args: argparse.Namespace) -> int:
    bundle = load_extensions()

    if not bundle.plugins:
        if getattr(args, "json", False):
            print("[]")
        else:
            print("No external plugins loaded.")
        return 0

    if getattr(args, "json", False):
        output_list(bundle.plugins, True, format_plugin, plugin_to_dict)
    else:
        print("Loaded plugins:")
        output_list(bundle.plugins, False, format_plugin, plugin_to_dict)
    return 0
