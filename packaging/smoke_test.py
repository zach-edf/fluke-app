#!/usr/bin/env python3
"""Smoke-test a packaged Fluke Community desktop build.

Launches the packaged binary with ``--self-test``, which initializes the full
service stack (SQLite store under the platform app-data dir, BLE adapter import,
bundled workflows, plugin discovery) and exits 0 without opening a window or
requiring BLE hardware.

Usage::

    python packaging/smoke_test.py                      # auto-locate the build
    python packaging/smoke_test.py path/to/executable   # explicit path

Exit code is 0 on success, non-zero on failure. Designed to be wired into CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

APP_NAME = "FlukeCommunity"


def _candidate_paths(repo_root: Path) -> list[Path]:
    dist = repo_root / "dist"
    candidates = [
        # Windows one-dir
        dist / APP_NAME / f"{APP_NAME}.exe",
        # Linux / generic one-dir
        dist / APP_NAME / APP_NAME,
        # macOS .app bundle
        dist / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME,
    ]
    return candidates


def _locate_binary(explicit: str | None, repo_root: Path) -> Path | None:
    if explicit:
        path = Path(explicit)
        return path if path.exists() else None
    for candidate in _candidate_paths(repo_root):
        if candidate.exists():
            return candidate
    return None


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    explicit = argv[1] if len(argv) > 1 else None
    binary = _locate_binary(explicit, repo_root)
    if binary is None:
        print("smoke_test: could not locate a packaged binary.", file=sys.stderr)
        print("Looked for:", file=sys.stderr)
        for candidate in _candidate_paths(repo_root):
            print(f"  {candidate}", file=sys.stderr)
        return 2

    print(f"smoke_test: launching {binary} --self-test")
    env = dict(os.environ)
    # Ensure Qt can initialize without a display if the self-test ever touches it.
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        result = subprocess.run(
            [str(binary), "--self-test"],
            timeout=120,
            capture_output=True,
            text=True,
            env=env,
        )
    except subprocess.TimeoutExpired:
        print("smoke_test: FAILED - binary did not exit within 120s.", file=sys.stderr)
        return 3

    if result.stdout:
        print(result.stdout, end="")
    if result.stderr:
        print(result.stderr, end="", file=sys.stderr)

    if result.returncode != 0:
        print(f"smoke_test: FAILED - exit code {result.returncode}.", file=sys.stderr)
        return result.returncode

    workflow_check = _check_bundled_workflows(binary, repo_root)
    if workflow_check is not None:
        print(f"smoke_test: FAILED - {workflow_check}", file=sys.stderr)
        return 4

    print("smoke_test: PASSED")
    return 0


def _check_bundled_workflows(binary: Path, repo_root: Path) -> str | None:
    """Verify the bundle ships every built-in workflow pack from this checkout.

    Guards against building from a stale interpreter whose fluke-community
    install points at different sources than this repo.
    """
    expected = {path.name for path in (repo_root / "workflows").glob("*.json")}
    if not expected:
        return None
    bundle_dirs = [
        binary.parent / "_internal" / "fluke_app" / "workflows",
        binary.parent / "_internal" / "workflows",
        # macOS .app layout
        binary.parent.parent / "Resources" / "fluke_app" / "workflows",
    ]
    for bundle_dir in bundle_dirs:
        if bundle_dir.exists():
            bundled = {path.name for path in bundle_dir.glob("*.json")}
            missing = expected - bundled
            if missing:
                return (
                    f"bundle at {bundle_dir} is missing workflow pack(s): "
                    f"{', '.join(sorted(missing))} - was the build run from this "
                    "repo's environment?"
                )
            return None
    return None  # layout unknown; do not fail the smoke test on it


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
