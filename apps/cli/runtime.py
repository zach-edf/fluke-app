from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from fluke_app import DeviceManager, EventBus, ReadingStreamService
from fluke_plugins import build_profile_registry, build_workflow_catalog, load_plugin_bundle
from fluke_store import FlukeStore


def configure_logging(verbose: bool = False) -> None:
    """Set up Python logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def default_database_path() -> str:
    """Return a platform-appropriate default database path.

    macOS:   ~/Library/Application Support/fluke-community/fluke.db
    Linux:   ~/.local/share/fluke-community/fluke.db
    Windows: %LOCALAPPDATA%/fluke-community/fluke.db
    Fallback: data/fluke.db
    """
    app_name = "fluke-community"
    if sys.platform == "darwin":
        db_dir = Path.home() / "Library" / "Application Support" / app_name
    elif sys.platform == "win32":
        db_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / app_name
    elif sys.platform.startswith("linux"):
        db_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / app_name
    else:
        db_dir = Path("data")
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "fluke.db")


def require_bleak_adapter() -> type[object]:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package. Install `requirements.txt`.") from exc
    return BleakAdapter


def build_device_manager() -> DeviceManager:
    bleak_adapter_cls = require_bleak_adapter()
    return DeviceManager(
        ble_adapter=bleak_adapter_cls(),
        profile_registry=build_profile_registry(),
        event_bus=EventBus(),
        reading_stream=ReadingStreamService(),
    )


def open_store(path: str | None = None) -> FlukeStore:
    return FlukeStore(path or default_database_path())


def load_extensions():
    return load_plugin_bundle()


def build_workflows():
    return build_workflow_catalog()
