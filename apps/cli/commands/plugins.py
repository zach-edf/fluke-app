from __future__ import annotations

import argparse

from apps.cli.runtime import load_extensions


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("plugins", help="Inspect loaded profile and workflow plugins")
    plugin_subparsers = parser.add_subparsers(dest="plugins_command", required=True)

    list_parser = plugin_subparsers.add_parser("list", help="List discovered plugins")
    list_parser.set_defaults(func=handle_list)


async def handle_list(args: argparse.Namespace) -> int:
    del args
    bundle = load_extensions()
    if not bundle.plugins:
        print("No external plugins loaded.")
        return 0

    print("Loaded plugins:")
    for plugin in bundle.plugins:
        print(f"- {plugin.manifest.name} ({plugin.manifest.plugin_id}) v{plugin.manifest.version}")
        if plugin.manifest.description:
            print(f"  description={plugin.manifest.description}")
        if plugin.profiles:
            print(f"  profiles={', '.join(profile.profile_id for profile in plugin.profiles)}")
        if plugin.workflow_paths:
            print(f"  workflow_paths={', '.join(str(path) for path in plugin.workflow_paths)}")
        if plugin.fixture_paths:
            print(f"  fixture_paths={', '.join(str(path) for path in plugin.fixture_paths)}")
    return 0
