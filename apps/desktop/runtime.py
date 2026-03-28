from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import threading

from apps.desktop.presenters import AppPresenter
from fluke_app import DeviceManager, EventBus, ReadingStreamService
from fluke_plugins import build_profile_registry, build_workflow_catalog
from fluke_store import FlukeStore


@dataclass(slots=True)
class DesktopRuntime:
    presenter: AppPresenter
    runner: "AsyncRunner"
    store: FlukeStore
    _closed: bool = False

    def submit(self, coro: object) -> object:
        return self.runner.submit(coro)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.submit(self.presenter.shutdown()).result(timeout=5)
        except Exception:
            pass
        self.runner.close()
        self.store.close()


class AsyncRunner:
    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="desktop-async")
        self._thread.start()
        self._ready.wait()

    def submit(self, coro: object) -> object:
        if self._loop is None:
            raise RuntimeError("Async runner is not ready.")
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def close(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)
        self._loop = None

    def _run_loop(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.close()


def build_runtime(
    *,
    ble_adapter: object | None = None,
    store_path: str | Path = "data/fluke.db",
    app_version: str = "0.1.0",
) -> DesktopRuntime:
    adapter = ble_adapter if ble_adapter is not None else _build_bleak_adapter()
    store = FlukeStore(store_path)
    profile_registry = build_profile_registry()
    workflow_catalog = build_workflow_catalog()
    manager = DeviceManager(
        ble_adapter=adapter,
        profile_registry=profile_registry,
        event_bus=EventBus(),
        reading_stream=ReadingStreamService(),
    )
    return DesktopRuntime(
        presenter=AppPresenter(manager, store, app_version=app_version, workflow_catalog=workflow_catalog),
        runner=AsyncRunner(),
        store=store,
    )


def _build_bleak_adapter() -> object:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package. Install `requirements.txt`.") from exc
    return BleakAdapter()
