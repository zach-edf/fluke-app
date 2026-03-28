from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"
for entry in (ROOT, PACKAGES):
    text = str(entry)
    if text not in sys.path:
        sys.path.insert(0, text)

from fluke_app import export_debug_bundle, load_workflow_catalog
from fluke_plugins import build_profile_registry, load_plugin_bundle


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a debug bundle zip for issue reports.")
    parser.add_argument("--output", required=True)
    parser.add_argument("--database", default="data/fluke.db")
    args = parser.parse_args()

    print(
        export_debug_bundle(
            args.output,
            profile_registry=build_profile_registry(),
            workflow_catalog=load_workflow_catalog(extra_paths=list(load_plugin_bundle().workflow_paths)),
            plugin_bundle=load_plugin_bundle(),
            database_path=args.database,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
