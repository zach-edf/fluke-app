from __future__ import annotations

import os
import sys

from apps.desktop.bootstrap import ensure_repo_paths

ensure_repo_paths()


def _run_self_test() -> int:
    """Initialize the desktop service stack and exit without opening a window.

    This exercises the parts of startup that are most likely to break in a
    packaged build -- importing the BLE backend (winrt / CoreBluetooth),
    resolving the default SQLite path under the platform app-data dir, loading
    bundled workflows, and discovering plugins -- but never creates a
    QApplication, so it can run headless in CI without a display.
    """
    from apps.desktop.runtime import build_runtime

    runtime = build_runtime()
    try:
        catalog = runtime.presenter.workflow_catalog
        workflow_count = len(catalog.list())
    finally:
        runtime.close()
    print(
        f"fluke-desktop self-test OK: store + BLE adapter + {workflow_count} workflow(s) initialized.",
        flush=True,
    )
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if "--self-test" in argv or os.environ.get("FLUKE_SELF_TEST"):
        try:
            return _run_self_test()
        except Exception as exc:  # noqa: BLE001 - report any startup failure
            print(f"fluke-desktop self-test FAILED: {exc}", file=sys.stderr)
            return 1

    from apps.desktop.app import run

    try:
        return run()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
