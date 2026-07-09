"""Filesystem path helpers that behave correctly in packaged (frozen) builds.

The desktop app can run either from a source checkout or from a PyInstaller
bundle. In a bundle, ``sys.frozen`` is set and ``sys._MEIPASS`` points at the
directory where bundled data files (``workflows/``, ``plugins/``) are unpacked.
Source-relative path math (``Path(__file__).parents[...]``) does not resolve to
those data directories once frozen, so callers must consult ``bundle_root``
first.

This module is intentionally dependency-free (stdlib only) so it can live in the
pure ``fluke_core`` layer.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return True when running from a PyInstaller (or similar) bundle."""
    return bool(getattr(sys, "frozen", False))


def bundle_root() -> Path | None:
    """Return the bundled data root when frozen, otherwise ``None``.

    For PyInstaller one-dir and one-file builds this is ``sys._MEIPASS`` -- the
    location where ``datas`` entries are extracted at runtime.
    """
    if not is_frozen():
        return None
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    # Fall back to the executable's directory if _MEIPASS is unavailable.
    return Path(sys.executable).resolve().parent


def bundled_data_dir(name: str) -> Path | None:
    """Return ``<bundle_root>/<name>`` when frozen and it exists, else ``None``."""
    root = bundle_root()
    if root is None:
        return None
    candidate = root / name
    return candidate if candidate.exists() else None


def user_data_dir(app_name: str = "fluke-community") -> Path:
    """Return the platform user data directory for this app.

    macOS:   ~/Library/Application Support/<app_name>
    Windows: %LOCALAPPDATA%/<app_name>
    Linux:   $XDG_DATA_HOME/<app_name> or ~/.local/share/<app_name>
    Fallback: ./data

    The directory is resolved lazily and never created here, so calling this
    for display purposes has no filesystem side effects. Callers that write
    must ``mkdir(parents=True, exist_ok=True)`` first.
    """
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / app_name
    if sys.platform.startswith("linux"):
        return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / app_name
    return Path("data")
