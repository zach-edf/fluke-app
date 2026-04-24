from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from apps.cli._bootstrap import ensure_repo_paths

ensure_repo_paths()

from apps.cli.commands.debug import _download_logging_data, _probe_device, _transact_characteristic, _write_logging_config
from fluke_protocol.profiles.fluke_376fc import (
    FLUKE_LOGGING_BUFFER_UUID,
    FLUKE_LOGGING_BYTES_PER_BLOCK,
    FLUKE_LOGGING_CAPACITY_UUID,
    FLUKE_LOGGING_CONFIG_UUID,
    FLUKE_LOGGING_CONTROL_POINT_UUID,
    FLUKE_LOGGING_SERVICE_UUID,
    FLUKE_LOGGING_STATUS_UUID,
    Fluke376FCLoggingStatus,
)
from apps.cli.main import build_parser
from fluke_ble.adapter import BleCharacteristicInfo, BleDevice
from fluke_testing import FakeBleAdapter, FakeBleService


class _ProbeFakeAdapter(FakeBleAdapter):
    def __init__(self) -> None:
        super().__init__(
            devices=[
                BleDevice(
                    id="meter-probe",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:FF",
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ],
            services_by_device={
                "meter-probe": [
                    FakeBleService(
                        uuid="service-1",
                        description="Probe Service",
                        characteristics=(
                            BleCharacteristicInfo(uuid="char-read", properties=("read",)),
                            BleCharacteristicInfo(uuid="char-notify", properties=("notify",)),
                        ),
                    )
                ]
            },
        )
        self._read_payloads = {"char-read": bytes.fromhex("01 02 03")}

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:
        await super().read(device_id, characteristic_uuid)
        return self._read_payloads.get(characteristic_uuid, b"")


class _LoggingConfigFakeAdapter(FakeBleAdapter):
    def __init__(self) -> None:
        super().__init__(
            devices=[
                BleDevice(
                    id="meter-config",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:11",
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ]
        )
        self.payload = bytes.fromhex("93 03 00 00 48 01 02 00")

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:
        await super().read(device_id, characteristic_uuid)
        if characteristic_uuid == FLUKE_LOGGING_CONFIG_UUID:
            return self.payload
        return b""

    async def write(self, device_id: str, characteristic_uuid: str, data: bytes) -> None:
        await super().write(device_id, characteristic_uuid, data)
        if characteristic_uuid == FLUKE_LOGGING_CONFIG_UUID:
            self.payload = bytes(data)


class _LoggingDownloadFakeAdapter(FakeBleAdapter):
    def __init__(self) -> None:
        super().__init__(
            devices=[
                BleDevice(
                    id="meter-download",
                    name="Fluke 376 FC",
                    address="AA:BB:CC:DD:EE:22",
                    metadata={"advertisement_name": "Fluke 376 FC"},
                )
            ],
            services_by_device={
                "meter-download": [
                    FakeBleService(
                        uuid=FLUKE_LOGGING_SERVICE_UUID,
                        description="Device Logging",
                        characteristics=(
                            BleCharacteristicInfo(uuid=FLUKE_LOGGING_STATUS_UUID, properties=("read", "notify")),
                            BleCharacteristicInfo(
                                uuid=FLUKE_LOGGING_CONTROL_POINT_UUID,
                                properties=("read", "write", "notify", "write-without-response"),
                            ),
                            BleCharacteristicInfo(uuid=FLUKE_LOGGING_BUFFER_UUID, properties=("notify",)),
                            BleCharacteristicInfo(uuid=FLUKE_LOGGING_CAPACITY_UUID, properties=("read",)),
                        ),
                    )
                ]
            },
        )
        self.status = Fluke376FCLoggingStatus(state_code=0, bytes_logged=36, blocks_logged=2)
        self.capacity = (1024).to_bytes(4, byteorder="little", signed=False)
        self.buffer_chunks = [
            bytes.fromhex("01 04 00 00 a5 00 6b 1c d7 69 99 1c d7 69 12 00 00 00"),
            bytes.fromhex("20 01 01 01 00 00 04 00 fe ff 06 00 00 00 00 00 00 00"),
        ]

    async def read(self, device_id: str, characteristic_uuid: str) -> bytes:
        await super().read(device_id, characteristic_uuid)
        if characteristic_uuid == FLUKE_LOGGING_STATUS_UUID:
            return self.status.to_payload()
        if characteristic_uuid == FLUKE_LOGGING_CAPACITY_UUID:
            return self.capacity
        if characteristic_uuid == FLUKE_LOGGING_CONTROL_POINT_UUID:
            return b"\x00"
        return b""

    async def write(
        self,
        device_id: str,
        characteristic_uuid: str,
        data: bytes,
        response: bool | None = None,
    ) -> None:
        await super().write(device_id, characteristic_uuid, data, response=response)
        if characteristic_uuid != FLUKE_LOGGING_CONTROL_POINT_UUID:
            return
        if data == b"\x83":
            self.status = Fluke376FCLoggingStatus(state_code=4, bytes_logged=36, blocks_logged=2)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_STATUS_UUID, self.status.to_payload())
            return
        if data == b"\x86":
            self.status = Fluke376FCLoggingStatus(state_code=0, bytes_logged=36, blocks_logged=2)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_STATUS_UUID, self.status.to_payload())
            return
        if len(data) == 9 and data[0] == 0x84:
            start_block = int.from_bytes(data[1:5], byteorder="little", signed=False)
            block_count = int.from_bytes(data[5:9], byteorder="little", signed=False)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_CONTROL_POINT_UUID, b"\x02")
            for chunk in self.buffer_chunks[start_block - 1 : start_block - 1 + block_count]:
                await self._emit_if_subscribed(device_id, FLUKE_LOGGING_BUFFER_UUID, chunk)
            await self._emit_if_subscribed(device_id, FLUKE_LOGGING_CONTROL_POINT_UUID, b"\x03")

    async def _emit_if_subscribed(self, device_id: str, characteristic_uuid: str, payload: bytes) -> None:
        if (device_id, characteristic_uuid.lower()) in self.subscription_keys:
            await self.emit(device_id, characteristic_uuid, payload)


class DebugProbeTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_device_reads_characteristics_and_captures_notifications(self) -> None:
        adapter = _ProbeFakeAdapter()
        await adapter.connect("meter-probe")

        probe_task = asyncio.create_task(
            _probe_device(
                adapter=adapter,
                device_id="meter-probe",
                read_characteristics=True,
                notify_seconds=0.05,
            )
        )
        await asyncio.sleep(0.01)
        await adapter.emit("meter-probe", "char-notify", bytes.fromhex("aa bb"))

        report = await probe_task

        self.assertEqual(report["device_id"], "meter-probe")
        self.assertEqual(len(report["services"]), 1)
        chars = report["services"][0]["characteristics"]
        self.assertEqual(chars[0]["read_hex"], "01 02 03")
        self.assertEqual(chars[0]["read_len"], 3)
        self.assertEqual(chars[1]["notification_count"], 1)
        self.assertEqual(chars[1]["notifications"][0]["hex"], "aa bb")

    async def test_transact_characteristic_can_read_without_writing(self) -> None:
        adapter = _ProbeFakeAdapter()
        await adapter.connect("meter-probe")

        report = await _transact_characteristic(
            adapter=adapter,
            device_id="meter-probe",
            characteristic_uuid="char-read",
            read_before=True,
            write_hex=None,
            write_mode="auto",
            read_after=False,
            notify_seconds=0.0,
            settle_seconds=0.0,
        )

        self.assertEqual(report["characteristic_uuid"], "char-read")
        self.assertEqual(report["service_uuid"], "service-1")
        self.assertEqual(report["read_before_result"]["hex"], "01 02 03")
        self.assertEqual(report["notification_count"], 0)

    async def test_transact_characteristic_forwards_write_mode(self) -> None:
        adapter = _ProbeFakeAdapter()
        await adapter.connect("meter-probe")

        report = await _transact_characteristic(
            adapter=adapter,
            device_id="meter-probe",
            characteristic_uuid="char-read",
            read_before=False,
            write_hex="01",
            write_mode="no-response",
            read_after=False,
            notify_seconds=0.0,
            settle_seconds=0.0,
        )

        self.assertTrue(report["write_ok"])
        self.assertEqual(report["write_mode"], "no-response")
        self.assertEqual(adapter.write_log, [("meter-probe", "char-read", b"\x01", False)])

    async def test_write_logging_config_round_trips(self) -> None:
        adapter = _LoggingConfigFakeAdapter()
        await adapter.connect("meter-config")

        report = await _write_logging_config(
            adapter=adapter,
            device_id="meter-config",
            interval_seconds=330,
            duration_seconds=270180,
            read_before=True,
            read_after=True,
        )

        self.assertTrue(report["write_ok"])
        self.assertEqual(report["read_before"]["payload_hex"], "93 03 00 00 48 01 02 00")
        self.assertEqual(report["read_after"]["payload_hex"], "4a 01 00 00 64 1f 04 00")

    async def test_download_logging_data_runs_validated_flow(self) -> None:
        adapter = _LoggingDownloadFakeAdapter()
        await adapter.connect("meter-download")

        output_path = Path.cwd() / "artifacts" / "test-logging-download.bin"
        output_path.unlink(missing_ok=True)
        try:
            report = await _download_logging_data(
                adapter=adapter,
                device_id="meter-download",
                data_output=output_path,
                max_blocks_per_request=500,
                command_timeout_seconds=0.5,
            )
            downloaded_bytes = output_path.read_bytes()
        finally:
            output_path.unlink(missing_ok=True)

        self.assertTrue(report["did_lock_for_download"])
        self.assertEqual(report["status_before"]["state_label"], "idle")
        self.assertEqual(report["status_locked"]["state_label"], "locked_for_download")
        self.assertEqual(report["downloaded_bytes"], 36)
        self.assertEqual(report["downloaded_blocks"], 2)
        self.assertEqual(report["status_after"]["state_label"], "idle")
        self.assertEqual(len(report["decoded_sessions"]), 1)
        self.assertEqual(report["decoded_sessions"][0]["interval_seconds"], 165)
        self.assertEqual(downloaded_bytes, b"".join(adapter.buffer_chunks))
        self.assertEqual(adapter.write_log[0][2], b"\x83")
        self.assertEqual(
            adapter.write_log[1][2],
            b"\x84" + (1).to_bytes(4, byteorder="little") + (2).to_bytes(4, byteorder="little"),
        )
        self.assertEqual(adapter.write_log[-1][2], b"\x86")

    def test_cli_parser_accepts_debug_probe_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--json",
                "debug",
                "probe",
                "--device",
                "meter-probe",
                "--read",
                "--notify-seconds",
                "0.5",
                "--output",
                "artifacts/probe.json",
            ]
        )

        self.assertEqual(args.command, "debug")
        self.assertEqual(args.debug_command, "probe")
        self.assertTrue(args.json)
        self.assertTrue(args.read)
        self.assertEqual(args.notify_seconds, 0.5)
        self.assertEqual(args.output, "artifacts/probe.json")

    def test_cli_parser_accepts_debug_transact_write_mode(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "debug",
                "transact",
                "--device",
                "meter-probe",
                "--char",
                "char-read",
                "--write-hex",
                "01",
                "--write-mode",
                "no-response",
                "--read-after",
            ]
        )

        self.assertEqual(args.command, "debug")
        self.assertEqual(args.debug_command, "transact")
        self.assertEqual(args.device, "meter-probe")
        self.assertEqual(args.char, "char-read")
        self.assertEqual(args.write_hex, "01")
        self.assertEqual(args.write_mode, "no-response")
        self.assertTrue(args.read_after)

    def test_cli_parser_accepts_debug_logging_config_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "--json",
                "debug",
                "logging-config",
                "--device",
                "meter-probe",
                "--output",
                "artifacts/logging-config.json",
            ]
        )

        self.assertEqual(args.command, "debug")
        self.assertEqual(args.debug_command, "logging-config")
        self.assertTrue(args.json)
        self.assertEqual(args.device, "meter-probe")
        self.assertEqual(args.output, "artifacts/logging-config.json")

    def test_cli_parser_accepts_debug_logging_download_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "debug",
                "logging-download",
                "--device",
                "meter-probe",
                "--data-output",
                "artifacts/logging-download.bin",
                "--max-blocks-per-request",
                "250",
                "--command-timeout-seconds",
                "6.0",
            ]
        )

        self.assertEqual(args.command, "debug")
        self.assertEqual(args.debug_command, "logging-download")
        self.assertEqual(args.device, "meter-probe")
        self.assertEqual(args.data_output, "artifacts/logging-download.bin")
        self.assertEqual(args.max_blocks_per_request, 250)
        self.assertEqual(args.command_timeout_seconds, 6.0)

    def test_cli_parser_accepts_debug_logging_config_set_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "debug",
                "logging-config-set",
                "--device",
                "meter-probe",
                "--interval-seconds",
                "915",
                "--duration-seconds",
                "131400",
                "--read-before",
                "--read-after",
            ]
        )

        self.assertEqual(args.command, "debug")
        self.assertEqual(args.debug_command, "logging-config-set")
        self.assertEqual(args.interval_seconds, 915)
        self.assertEqual(args.duration_seconds, 131400)
        self.assertTrue(args.read_before)
        self.assertTrue(args.read_after)


if __name__ == "__main__":
    unittest.main()
