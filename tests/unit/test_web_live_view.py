from __future__ import annotations

import asyncio
import json
import unittest

from tests.unit._helpers import measurement_payload

from aiohttp.test_utils import TestClient, TestServer

from fluke_app.device_manager import DeviceManager
from fluke_ble.adapter import BleDevice
from fluke_protocol import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import FLUKE_MEAS_UUID, FLUKE_STATUS_UUID, Fluke376FCProfile
from fluke_testing import FakeBleAdapter, ReplayFrame, ReplayScenario
from fluke_web import LiveState, WebLiveServer, build_urls, enumerate_lan_ips
from fluke_web.qr import render_qr_ascii


def _build_manager() -> tuple[FakeBleAdapter, DeviceManager]:
    adapter = FakeBleAdapter(
        devices=[
            BleDevice(
                id="meter-web",
                name="Fluke 376 FC",
                address="AA:BB:CC:DD:EE:F0",
                rssi=-44,
                metadata={"advertisement_name": "Fluke 376 FC"},
            )
        ]
    )
    manager = DeviceManager(adapter, ProfileRegistry([Fluke376FCProfile()]))
    return adapter, manager


async def _emit_voltage(adapter: FakeBleAdapter, device_id: str, text: str) -> None:
    scenario = ReplayScenario(
        (
            ReplayFrame(FLUKE_STATUS_UUID, bytes([0x17])),
            ReplayFrame(FLUKE_MEAS_UUID, measurement_payload(text, "dc")),
        )
    )
    await scenario.run(adapter, device_id)


class LiveStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_tracks_min_max_avg_and_staleness(self) -> None:
        adapter, manager = _build_manager()
        state = LiveState(stale_after_s=0.05)
        manager.subscribe_readings(state.on_reading)

        await manager.scan(timeout_s=0.1)
        await manager.establish_session("meter-web")
        await _emit_voltage(adapter, "meter-web", "10.00 V")
        await _emit_voltage(adapter, "meter-web", "20.00 V")

        snap = state.snapshot()
        self.assertEqual(snap["sample_count"], 2)
        self.assertAlmostEqual(snap["min_value"], 10.0)
        self.assertAlmostEqual(snap["max_value"], 20.0)
        self.assertAlmostEqual(snap["avg_value"], 15.0)
        self.assertFalse(snap["stale"])
        self.assertEqual(snap["connection_status"], "connected")
        self.assertEqual(len(snap["history"]), 2)

        await asyncio.sleep(0.08)
        self.assertTrue(state.is_stale())
        await manager.disconnect()


class WebEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.adapter, self.manager = _build_manager()
        self.state = LiveState(stale_after_s=5.0)
        self.server = WebLiveServer(self.state)
        self.manager.subscribe_readings(self.server.on_reading)
        self.client = TestClient(TestServer(self.server.app))
        await self.client.start_server()
        await self.manager.scan(timeout_s=0.1)
        await self.manager.establish_session("meter-web")

    async def asyncTearDown(self) -> None:
        await self.manager.disconnect()
        await self.client.close()

    async def test_serves_self_contained_page(self) -> None:
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("text/html", resp.headers["Content-Type"])
        body = await resp.text()
        self.assertIn("FLUKE", body)
        self.assertIn("<canvas", body)
        self.assertIn("new WebSocket", body)
        # Self-contained: no external network dependencies.
        self.assertNotIn("http://", body.replace('href="/api', ""))
        self.assertNotIn("cdn", body.lower())

    async def test_status_and_latest_json(self) -> None:
        await _emit_voltage(self.adapter, "meter-web", "12.34 V")

        status = await (await self.client.get("/api/status")).json()
        self.assertEqual(status["sample_count"], 1)
        self.assertAlmostEqual(status["reading"]["value"], 12.34)
        self.assertEqual(status["reading"]["unit"], "V")

        latest = await (await self.client.get("/api/latest")).json()
        self.assertAlmostEqual(latest["reading"]["value"], 12.34)
        self.assertFalse(latest["stale"])

    async def test_websocket_pushes_readings(self) -> None:
        ws = await self.client.ws_connect("/ws")
        # First frame is the immediate snapshot on connect.
        first = json.loads((await ws.receive()).data)
        self.assertIn("connection_status", first)

        await _emit_voltage(self.adapter, "meter-web", "48.00 V")
        pushed = json.loads((await asyncio.wait_for(ws.receive(), timeout=2.0)).data)
        self.assertAlmostEqual(pushed["reading"]["value"], 48.0)
        self.assertEqual(pushed["sample_count"], 1)
        self.assertIn("history", pushed)
        await ws.close()


class TokenGateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.server = WebLiveServer(LiveState(), token="s3cret")
        self.client = TestClient(TestServer(self.server.app))
        await self.client.start_server()

    async def asyncTearDown(self) -> None:
        await self.client.close()

    async def test_rejects_without_token(self) -> None:
        self.assertEqual((await self.client.get("/")).status, 401)
        self.assertEqual((await self.client.get("/api/status")).status, 401)

    async def test_accepts_with_token(self) -> None:
        self.assertEqual((await self.client.get("/?token=s3cret")).status, 200)
        self.assertEqual((await self.client.get("/api/status?token=s3cret")).status, 200)

    async def test_websocket_requires_token(self) -> None:
        with self.assertRaises(Exception):
            await self.client.ws_connect("/ws")
        ws = await self.client.ws_connect("/ws?token=s3cret")
        await ws.close()


class HelperTests(unittest.TestCase):
    def test_enumerate_lan_ips_includes_loopback(self) -> None:
        ips = enumerate_lan_ips()
        self.assertIn("127.0.0.1", ips)

    def test_build_urls_embeds_token(self) -> None:
        urls = build_urls(["192.168.1.5"], 8765, token="abc")
        self.assertEqual(urls, ["http://192.168.1.5:8765/?token=abc"])

    def test_qr_renders_or_gracefully_none(self) -> None:
        result = render_qr_ascii("http://192.168.1.5:8765/")
        # qrcode is an optional extra; either a string or None is acceptable.
        self.assertTrue(result is None or isinstance(result, str))


if __name__ == "__main__":
    unittest.main()
