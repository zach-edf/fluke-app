from __future__ import annotations

from fluke_app import DeviceManager, EventBus, ReadingStreamService
from fluke_plugins import build_profile_registry, build_workflow_catalog, load_plugin_bundle
from fluke_store import FlukeStore


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


def open_store(path: str) -> FlukeStore:
    return FlukeStore(path)


def load_extensions():
    return load_plugin_bundle()


def build_workflows():
    return build_workflow_catalog()
