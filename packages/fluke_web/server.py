from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import WSMsgType, web

from fluke_core.models.reading import Reading
from fluke_web.page import render_page
from fluke_web.state import LiveState

logger = logging.getLogger(__name__)


class WebLiveServer:
    """LAN-only live web view for a single meter's reading stream.

    The server is deliberately a *sink*: it exposes :meth:`on_reading` and
    :meth:`set_connection_status` which the CLI wires to
    :class:`DeviceManager` callbacks. It never calls back into the device, so
    there is no code path through which the web page could control the meter
    (read-only by construction).

    Build one, then either:

    * mount ``server.app`` under an ``aiohttp`` test client (tests), or
    * call :meth:`start` / :meth:`stop` to bind a real TCP site (CLI).
    """

    def __init__(
        self,
        state: LiveState | None = None,
        *,
        token: str | None = None,
    ) -> None:
        self.state = state or LiveState()
        self._token = token or None
        self._clients: set[web.WebSocketResponse] = set()
        self._runner: web.AppRunner | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.app = self._build_app()

    # -- app wiring --------------------------------------------------------

    def _build_app(self) -> web.Application:
        app = web.Application()
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/ws", self._handle_ws)
        app.router.add_get("/api/status", self._handle_status)
        app.router.add_get("/api/latest", self._handle_latest)
        app.router.add_get("/healthz", self._handle_health)
        app.on_shutdown.append(self._on_shutdown)
        return app

    def _authorized(self, request: web.Request) -> bool:
        if self._token is None:
            return True
        return request.query.get("token") == self._token

    # -- HTTP handlers -----------------------------------------------------

    async def _handle_index(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.Response(status=401, text="Unauthorized: missing or invalid token.")
        return web.Response(text=render_page(), content_type="text/html")

    async def _handle_status(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(self.state.snapshot(include_history=True))

    async def _handle_latest(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)
        return web.json_response(self.state.latest_payload())

    async def _handle_health(self, request: web.Request) -> web.StreamResponse:
        return web.json_response({"ok": True, "clients": len(self._clients)})

    async def _handle_ws(self, request: web.Request) -> web.StreamResponse:
        if not self._authorized(request):
            return web.json_response({"error": "unauthorized"}, status=401)

        ws = web.WebSocketResponse(heartbeat=20.0)
        await ws.prepare(request)
        self._clients.add(ws)
        # Send an immediate snapshot so a freshly (re)connected client renders
        # without waiting for the next reading.
        try:
            await ws.send_str(self._encode(self.state.snapshot(include_history=True)))
            async for msg in ws:
                # The page never sends commands; ignore inbound frames except
                # to notice a close. This keeps the surface strictly read-only.
                if msg.type in (WSMsgType.ERROR, WSMsgType.CLOSE):
                    break
        finally:
            self._clients.discard(ws)
        return ws

    # -- ingestion (device-manager facing) --------------------------------

    def on_reading(self, reading: Reading) -> None:
        self.state.on_reading(reading)
        self._broadcast(self.state.snapshot(include_history=True))

    def set_connection_status(self, status: str, detail: str = "") -> None:
        self.state.set_connection_status(status, detail)
        self._broadcast(self.state.snapshot(include_history=False))

    # -- broadcast ---------------------------------------------------------

    def _encode(self, payload: dict[str, Any]) -> str:
        return json.dumps(payload)

    def _broadcast(self, payload: dict[str, Any]) -> None:
        if not self._clients:
            return
        text = self._encode(payload)
        loop = self._loop or self._running_loop()
        if loop is None:
            return
        for ws in list(self._clients):
            # send_str returns a coroutine; schedule it on the server loop so
            # this method is safe to call from synchronous BLE callbacks.
            loop.call_soon_threadsafe(lambda w=ws, t=text: asyncio.ensure_future(self._safe_send(w, t)))

    async def _safe_send(self, ws: web.WebSocketResponse, text: str) -> None:
        try:
            if not ws.closed:
                await ws.send_str(text)
        except Exception:
            self._clients.discard(ws)

    def _running_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            return asyncio.get_running_loop()
        except RuntimeError:
            return None

    # -- lifecycle (CLI facing) -------------------------------------------

    async def start(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._loop = asyncio.get_running_loop()
        self._runner = web.AppRunner(self.app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, host=host, port=port)
        await site.start()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _on_shutdown(self, app: web.Application) -> None:
        for ws in list(self._clients):
            try:
                await ws.close(code=WSMsgType.CLOSE.value, message=b"server shutdown")
            except Exception:
                pass
        self._clients.clear()

    @property
    def client_count(self) -> int:
        return len(self._clients)
