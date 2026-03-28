from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading
from fluke_plugins.loader import PluginRegistration
from fluke_protocol.profiles.base import DeviceProfile


class ExampleExperimentalProfile(DeviceProfile):
    profile_id = "example_experimental_meter"
    model_name = "Example Experimental Meter"

    def matches(self, advertisement_name: str | None, metadata: dict[str, object]) -> bool:
        return (advertisement_name or "").startswith("Example Meter")

    def capabilities(self) -> list[str]:
        return ["live_primary_reading"]

    def notification_characteristics(self) -> list[str]:
        return ["0000feed-0000-1000-8000-00805f9b34fb"]

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        del characteristic_uuid
        timestamp = observed_at or datetime.now(timezone.utc)
        text = payload.decode("ascii", errors="ignore").strip() or "0.0 V"
        number = float(text.split()[0])
        return [
            Reading(
                timestamp_utc=timestamp,
                value=number,
                unit="V",
                measurement_type=MeasurementType.VOLTAGE_DC,
                status=ReadingStatus.OK,
                display_text=text,
                source_device_id=device_id,
                raw_payload=payload,
            )
        ]


def register_plugin(plugin_root: Path) -> PluginRegistration:
    del plugin_root
    return PluginRegistration(profiles=[ExampleExperimentalProfile()])
