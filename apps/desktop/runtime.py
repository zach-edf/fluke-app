from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from apps.cli.runtime import default_database_path
from apps.desktop.presenters import AppPresenter
from fluke_app import DeviceManager, EventBus, ReadingStreamService
from fluke_plugins import build_profile_registry, build_workflow_catalog
from fluke_store import FlukeStore


@dataclass(slots=True)
class DesktopRuntime:
    presenter: AppPresenter
    runner: object
    store: FlukeStore
    _closed: bool = False

    def submit(self, coro: object) -> object:
        return self.runner.submit(coro)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            future = self.submit(self.presenter.shutdown())
            self.runner.wait(future, timeout=5)
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

    def wait(self, future: object, timeout: float | None = None) -> Any:
        return future.result(timeout=timeout)

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


class LoopRunner:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def submit(self, coro: object) -> object:
        return self._loop.create_task(coro)

    def wait(self, future: object, timeout: float | None = None) -> Any:
        if future.done():
            return future.result()
        if self._loop.is_running():
            raise RuntimeError("Cannot synchronously wait while the Qt asyncio loop is still running.")
        return self._loop.run_until_complete(asyncio.wait_for(asyncio.shield(future), timeout=timeout))

    def close(self) -> None:
        if self._loop.is_running() or self._loop.is_closed():
            return
        pending = [task for task in asyncio.all_tasks(self._loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            self._loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        self._loop.close()


def build_runtime(
    *,
    ble_adapter: object | None = None,
    store_path: str | Path | None = None,
    app_version: str = "0.1.0",
    event_loop: asyncio.AbstractEventLoop | None = None,
) -> DesktopRuntime:
    adapter = ble_adapter if ble_adapter is not None else _build_bleak_adapter()
    store = FlukeStore(store_path or default_database_path())
    profile_registry = build_profile_registry()
    workflow_catalog = build_workflow_catalog()
    manager = DeviceManager(
        ble_adapter=adapter,
        profile_registry=profile_registry,
        event_bus=EventBus(),
        reading_stream=ReadingStreamService(),
    )
    runner = LoopRunner(event_loop) if event_loop is not None else AsyncRunner()
    return DesktopRuntime(
        presenter=AppPresenter(manager, store, app_version=app_version, workflow_catalog=workflow_catalog),
        runner=runner,
        store=store,
    )


def _build_bleak_adapter() -> object:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package. Install `requirements.txt`.") from exc
    return BleakAdapter()
