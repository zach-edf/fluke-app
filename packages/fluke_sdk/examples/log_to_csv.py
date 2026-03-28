from __future__ import annotations

import asyncio
from pathlib import Path

from fluke_sdk.bootstrap import ensure_repo_paths

ensure_repo_paths()

from fluke_app import ExportService, SessionRecorder, new_session
from fluke_app.export_service import SessionCsvExporter, SessionJsonExporter
from fluke_store import FlukeStore
from fluke_sdk import FlukeClient


async def main() -> int:
    client = FlukeClient()
    devices = await client.scan(timeout_s=5.0)
    if not devices:
        print("No devices found.")
        return 0

    store = FlukeStore(Path("data/sdk-example.db"))
    recorder = SessionRecorder(store.sessions, store.readings)
    export_service = ExportService(
        store.sessions,
        store.readings,
        SessionCsvExporter(),
        SessionJsonExporter(device_repo=store.devices),
    )

    try:
        device = await client.connect(devices[0].device_id)
        store.upsert_device(device)
        recorder.start(
            new_session(
                device_id=device.device_id,
                title="SDK Example",
                profile_id=device.profile_id,
            )
        )
        client.on_reading(recorder.on_reading)
        await asyncio.sleep(10)
        session = recorder.stop()
        if session is not None:
            export_service.export_csv(session.session_id, Path("exports/sdk-example.csv"))
            export_service.export_json(session.session_id, Path("exports/sdk-example.json"))
    finally:
        await client.close()
        store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
