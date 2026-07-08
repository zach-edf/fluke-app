from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from tests.unit._helpers import ROOT  # noqa: F401

from apps.cli.main import build_parser
from fluke_app import new_session
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.asset import Asset
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_store import FlukeStore


def _tmp_dir() -> Path:
    tmp = Path(__file__).resolve().parents[2] / ".test-tmp" / uuid4().hex
    tmp.mkdir(parents=True, exist_ok=False)
    return tmp


def _run(argv: list[str]) -> tuple[int, str]:
    import asyncio

    parser = build_parser()
    args = parser.parse_args(argv)
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = asyncio.run(args.func(args))
    return code, buffer.getvalue()


class CliAssetsTests(unittest.TestCase):
    def _seed(self) -> str:
        db_path = _tmp_dir() / "cli.db"
        store = FlukeStore(db_path)
        store.upsert_device(
            DeviceInfo(device_id="d1", ble_address="AA", model_name="M", profile_id="p", support_level="supported")
        )
        store.create_asset(Asset(asset_id="motor-1", name="Motor", asset_type="motor"))
        for month, value in [(1, 42.0), (7, 51.0)]:
            session = new_session(
                device_id="d1", title=f"run-{month}", asset_id="motor-1",
                started_at=datetime(2026, month, 1, tzinfo=timezone.utc),
            )
            store.sessions.create(session)
            store.readings.append(
                session.session_id,
                Reading(
                    timestamp_utc=datetime(2026, month, 1, tzinfo=timezone.utc),
                    value=value, unit="A", measurement_type=MeasurementType.CURRENT_INRUSH,
                    status=ReadingStatus.OK, display_text=f"{value} A", source_device_id="d1",
                    metadata={"unit_family": "current"},
                ),
            )
        store.close()
        return str(db_path)

    def test_assets_create_and_list_json(self) -> None:
        db = str(_tmp_dir() / "cli.db")
        code, _ = _run(["assets", "--database", db, "create", "--name", "Pump", "--type", "pump", "--id", "pump-1"])
        self.assertEqual(code, 0)

        code, out = _run(["--json", "assets", "--database", db, "list"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload), 1)
        self.assertEqual(payload[0]["asset_id"], "pump-1")
        self.assertEqual(payload[0]["asset_type"], "pump")

    def test_assets_show_lists_sessions(self) -> None:
        db = self._seed()
        code, out = _run(["--json", "assets", "--database", db, "show", "--asset", "motor-1"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["name"], "Motor")
        self.assertEqual(len(payload["sessions"]), 2)

    def test_assets_show_unknown_returns_error(self) -> None:
        db = str(_tmp_dir() / "cli.db")
        FlukeStore(Path(db)).close()
        code, out = _run(["assets", "--database", db, "show", "--asset", "nope"])
        self.assertEqual(code, 1)
        self.assertIn("Unknown asset", out)

    def test_assets_trend_json(self) -> None:
        db = self._seed()
        code, out = _run(["--json", "assets", "--database", db, "trend", "--asset", "motor-1"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["session_count"], 2)
        series = payload["series"][0]
        self.assertEqual(series["measurement"], "current_inrush")
        self.assertEqual([p["avg"] for p in series["points"]], [42.0, 51.0])

    def test_assets_trend_csv_output(self) -> None:
        db = self._seed()
        out_csv = _tmp_dir() / "trend.csv"
        code, out = _run(["assets", "--database", db, "trend", "--asset", "motor-1", "--csv-output", str(out_csv)])
        self.assertEqual(code, 0)
        self.assertTrue(out_csv.exists())
        self.assertIn("Wrote trend CSV", out)

    def test_sessions_list_filtered_by_asset(self) -> None:
        db = self._seed()
        code, out = _run(["--json", "sessions", "--database", db, "list", "--asset", "motor-1"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(len(payload), 2)
        self.assertTrue(all(s["asset_id"] == "motor-1" for s in payload))

    def test_sessions_assign_asset_roundtrip(self) -> None:
        db = self._seed()
        store = FlukeStore(Path(db))
        orphan = new_session(device_id="d1", title="orphan")
        store.sessions.create(orphan)
        store.close()

        code, _ = _run(["sessions", "--database", db, "assign-asset", "--session", orphan.session_id, "--asset", "motor-1"])
        self.assertEqual(code, 0)
        store = FlukeStore(Path(db))
        self.assertEqual(store.sessions.get(orphan.session_id).asset_id, "motor-1")
        store.close()

        code, _ = _run(["sessions", "--database", db, "assign-asset", "--session", orphan.session_id])
        self.assertEqual(code, 0)
        store = FlukeStore(Path(db))
        self.assertIsNone(store.sessions.get(orphan.session_id).asset_id)
        store.close()

    def test_parser_registers_assets_command(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["--json", "assets", "trend", "--asset", "a1", "--measurement", "current_inrush"])
        self.assertEqual(args.command, "assets")
        self.assertEqual(args.assets_command, "trend")
        self.assertTrue(args.json)
        self.assertEqual(args.asset, "a1")
        self.assertEqual(args.measurement, "current_inrush")


if __name__ == "__main__":
    unittest.main()
