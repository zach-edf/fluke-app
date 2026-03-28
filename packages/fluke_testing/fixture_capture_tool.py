from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path

from fluke_ble.adapter import BleAdapter
from fluke_protocol import ProfileRegistry


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    characteristic_uuid: str
    observed_at: datetime
    payload_hex: str


@dataclass(frozen=True, slots=True)
class CapturedFixture:
    device_id: str
    profile_id: str
    started_at: datetime
    ended_at: datetime
    frames: tuple[CapturedFrame, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "device_id": self.device_id,
            "profile_id": self.profile_id,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat(),
            "frames": [
                {
                    "characteristic_uuid": frame.characteristic_uuid,
                    "observed_at": frame.observed_at.isoformat(),
                    "payload_hex": frame.payload_hex,
                }
                for frame in self.frames
            ],
        }

    def export_json(self, path: str | Path) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_payload(), indent=2, ensure_ascii=True), encoding="utf-8")
        return str(target)


async def capture_fixture(
    adapter: BleAdapter,
    profile_registry: ProfileRegistry,
    *,
    device_id: str,
    profile_id: str,
    duration_s: float = 10.0,
    max_frames: int = 0,
) -> CapturedFixture:
    profile = profile_registry.get(profile_id)
    if profile is None:
        raise RuntimeError(f"Unknown profile {profile_id!r}.")

    started_at = datetime.now(timezone.utc)
    frames: list[CapturedFrame] = []
    finished = asyncio.Event()

    async def _on_payload(characteristic_uuid: str, payload: bytes) -> None:
        frames.append(
            CapturedFrame(
                characteristic_uuid=characteristic_uuid,
                observed_at=datetime.now(timezone.utc),
                payload_hex=payload.hex(),
            )
        )
        if max_frames and len(frames) >= max_frames:
            finished.set()

    await adapter.connect(device_id)
    characteristics = profile.notification_characteristics()
    try:
        for characteristic_uuid in characteristics:
            async def _callback(payload: bytes, *, _characteristic_uuid: str = characteristic_uuid) -> None:
                await _on_payload(_characteristic_uuid, payload)

            await adapter.subscribe(device_id, characteristic_uuid, _callback)

        if max_frames:
            try:
                await asyncio.wait_for(finished.wait(), timeout=duration_s)
            except asyncio.TimeoutError:
                pass
        else:
            await asyncio.sleep(duration_s)
    finally:
        for characteristic_uuid in characteristics:
            try:
                await adapter.unsubscribe(device_id, characteristic_uuid)
            except Exception:
                pass
        await adapter.disconnect(device_id)

    return CapturedFixture(
        device_id=device_id,
        profile_id=profile_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        frames=tuple(frames),
    )
