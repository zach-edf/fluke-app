from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGES = ROOT / "packages"

for path in (ROOT, PACKAGES):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_protocol.registry import ProfileRegistry
from fluke_protocol.profiles.fluke_376fc import (
    decode_logging_download_payload,
    FLUKE_ADV_SERVICE_UUID,
    FLUKE_MEAS_UUID,
    FLUKE_STATUS_UUID,
    Fluke376FCLoggingConfig,
    Fluke376FCLoggingStatus,
    Fluke376FCProfile,
    FlukeAdvancedClampFamilyProfile,
    FlukeClampMeterFamilyProfile,
)


def measurement_payload(primary: str, mode: str) -> bytes:
    display = primary.ljust(10)[:10].encode("ascii")
    mode_bytes = mode.ljust(5)[:5].encode("ascii")
    return b"\x00" + display + b"\x00" + mode_bytes


def pack_lsb_fields(widths: tuple[int, ...], values: tuple[int, ...]) -> bytes:
    current = 0
    offset = 0
    for width, value in zip(widths, values, strict=True):
        current |= (value & ((1 << width) - 1)) << offset
        offset += width
    return current.to_bytes((offset + 7) // 8, byteorder="little", signed=False)


def advanced_clamp_reading_payload(
    *,
    counts: int,
    state: int,
    decimal_places: int,
    magnitude: int,
    sign: int,
    unit_code: int,
    function_code: int,
) -> bytes:
    return pack_lsb_fields(
        (21, 4, 3, 3, 1, 8, 8, 7, 3, 5, 1),
        (counts, state, decimal_places, magnitude, sign, unit_code, function_code, 0, 0, 0, 0),
    )


def advanced_clamp_frame(
    primary: bytes,
    secondary: bytes,
    *,
    mode_attrs: tuple[int, int, int, int, int] = (0, 0, 0, 0, 0),
) -> bytes:
    return primary + secondary + pack_lsb_fields((4, 4, 4, 3, 1), mode_attrs)


class Fluke376FCProfileTests(unittest.TestCase):
    def test_registry_resolves_matches_as_scored_family_variants(self) -> None:
        registry = ProfileRegistry([FlukeClampMeterFamilyProfile(), FlukeAdvancedClampFamilyProfile(), Fluke376FCProfile()])
        match = registry.resolve("Fluke 374 FC", {"advertisement_name": "Fluke 374 FC"})
        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.profile_id, "fluke_clamp_meter_family")
        self.assertEqual(match.family_id, "fluke_clamp_meter")
        self.assertEqual(match.variant_id, "374fc")
        self.assertNotIn("device_logging_config", match.capabilities)

    def test_clamp_meter_family_exposes_logging_capability_only_for_supported_variants(self) -> None:
        profile = FlukeClampMeterFamilyProfile()
        match_374 = profile.create_match("Fluke 374 FC", {"advertisement_name": "Fluke 374 FC"})
        match_375 = profile.create_match("Fluke 375 FC", {"advertisement_name": "Fluke 375 FC"})
        self.assertIsNotNone(match_374)
        self.assertIsNotNone(match_375)
        assert match_374 is not None
        assert match_375 is not None
        self.assertNotIn("device_logging_config", match_374.capabilities)
        self.assertIn("device_logging_config", match_375.capabilities)

    def test_clamp_meter_family_detects_all_supported_variant_aliases(self) -> None:
        profile = FlukeClampMeterFamilyProfile()
        cases = {
            "376 FC": "376fc",
            "Fluke-375-FC": "375fc",
            "368fc": "368fc",
            "Fluke 369 FC": "369fc",
            "902FC": "902fc",
        }
        for label, expected_variant in cases.items():
            with self.subTest(label=label):
                match = profile.create_match(label, {"advertisement_name": label})
                self.assertIsNotNone(match)
                assert match is not None
                self.assertEqual(match.variant_id, expected_variant)

    def test_matches_fluke_376_name(self) -> None:
        profile = Fluke376FCProfile()
        self.assertTrue(profile.matches("Fluke 376 FC", {}))
        self.assertTrue(profile.matches(None, {"advertisement_name": "Shop 376FC"}))
        self.assertFalse(profile.matches("Random Sensor", {}))

    def test_matches_by_service_uuid_fallback(self) -> None:
        # Simulates Windows WinRT behaviour where adv name is None but the
        # advertised service UUID is present. FLUKE_ADV_SERVICE_UUID is what
        # the 376 FC includes in its advertisement packet; the MEAS/STATUS UUIDs
        # are GATT characteristics only visible after connecting.
        profile = Fluke376FCProfile()
        self.assertTrue(profile.matches(None, {"service_uuids": [FLUKE_ADV_SERVICE_UUID]}))
        self.assertTrue(profile.matches(None, {"service_uuids": [FLUKE_ADV_SERVICE_UUID, FLUKE_MEAS_UUID]}))
        self.assertFalse(profile.matches(None, {"service_uuids": [FLUKE_MEAS_UUID]}))
        self.assertFalse(profile.matches(None, {"service_uuids": ["00001234-0000-1000-8000-00805f9b34fb"]}))
        self.assertFalse(profile.matches(None, {}))

    def test_parse_dc_voltage_reading(self) -> None:
        profile = Fluke376FCProfile()
        observed_at = datetime(2026, 3, 27, 12, 0, tzinfo=timezone.utc)

        readings = profile.parse_notification(
            FLUKE_MEAS_UUID,
            measurement_payload("12.34 V", "dc"),
            "meter-1",
            observed_at=observed_at,
        )

        self.assertEqual(len(readings), 1)
        reading = readings[0]
        self.assertEqual(reading.timestamp_utc, observed_at)
        self.assertAlmostEqual(reading.value or 0.0, 12.34)
        self.assertEqual(reading.unit, "V")
        self.assertEqual(reading.measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(reading.status, ReadingStatus.OK)
        self.assertEqual(reading.mode, "dc")
        self.assertEqual(reading.metadata["function_key"], "dc_voltage")

    def test_parse_over_range_reading(self) -> None:
        profile = Fluke376FCProfile()

        readings = profile.parse_notification(
            FLUKE_MEAS_UUID,
            measurement_payload("OL mV", "dc"),
            "meter-1",
        )

        self.assertEqual(len(readings), 1)
        reading = readings[0]
        self.assertIsNone(reading.value)
        self.assertEqual(reading.unit, "mV")
        self.assertEqual(reading.measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(reading.status, ReadingStatus.OVER_RANGE)

    def test_status_notifications_are_cached_not_emitted(self) -> None:
        profile = Fluke376FCProfile()
        readings = profile.parse_notification(FLUKE_STATUS_UUID, bytes([123]), "meter-1")
        self.assertEqual(readings, [])

    def test_logging_config_decodes_interval_and_duration(self) -> None:
        config = Fluke376FCLoggingConfig.from_payload(bytes.fromhex("93 03 00 00 48 01 02 00"))
        self.assertEqual(config.interval_seconds, 915)
        self.assertEqual(config.duration_seconds, 131400)

    def test_logging_config_round_trips_payload(self) -> None:
        config = Fluke376FCLoggingConfig(
            interval_seconds=330,
            duration_seconds=270180,
        )
        self.assertEqual(config.to_payload().hex(" "), "4a 01 00 00 64 1f 04 00")

    def test_logging_config_supports_full_32_bit_interval_field(self) -> None:
        config = Fluke376FCLoggingConfig(interval_seconds=70000, duration_seconds=3600)
        self.assertEqual(config.to_payload().hex(" "), "70 11 01 00 10 0e 00 00")

    def test_logging_status_decodes_state_bytes_and_blocks(self) -> None:
        status = Fluke376FCLoggingStatus.from_payload(bytes.fromhex("00 24 00 00 00 02 00 00 00"))
        self.assertEqual(status.state_code, 0)
        self.assertEqual(status.state_label, "idle")
        self.assertEqual(status.bytes_logged, 36)
        self.assertEqual(status.blocks_logged, 2)

    def test_decode_logging_download_payload_parses_header_and_detail(self) -> None:
        payload = bytes.fromhex(
            "01 04 00 00 a5 00 6b 1c d7 69 99 1c d7 69 12 00 00 00 "
            "20 01 01 01 00 00 04 00 fe ff 06 00 00 00 00 00 00 00"
        )
        sessions = decode_logging_download_payload(payload)
        self.assertEqual(len(sessions), 1)
        session = sessions[0]
        self.assertEqual(session["primary_unit_code"], 4)
        self.assertEqual(session["primary_unit_label"], "A DC")
        self.assertEqual(session["interval_seconds"], 165)
        self.assertEqual(session["detail_count"], 1)
        detail = session["details"][0]
        self.assertEqual(detail["reading_index"], 0)
        self.assertEqual(detail["unit_label"], "A DC")
        self.assertEqual(detail["average"]["scaled_value"], 0.0)
        self.assertEqual(detail["maximum"]["scaled_value"], 0.4)
        self.assertEqual(detail["minimum"]["scaled_value"], -0.2)
        self.assertEqual(detail["capture_offset_seconds"], 6)
        self.assertEqual(detail["min_offset_seconds"], 0)

    def test_advanced_clamp_profile_parses_dual_readings_and_mode_attrs(self) -> None:
        profile = FlukeAdvancedClampFamilyProfile()
        observed_at = datetime(2026, 4, 9, 12, 0, tzinfo=timezone.utc)
        payload = advanced_clamp_frame(
            advanced_clamp_reading_payload(
                counts=123,
                state=0,
                decimal_places=1,
                magnitude=0,
                sign=0,
                unit_code=2,
                function_code=12,
            ),
            advanced_clamp_reading_payload(
                counts=45,
                state=0,
                decimal_places=2,
                magnitude=0,
                sign=0,
                unit_code=4,
                function_code=21,
            ),
            mode_attrs=(8, 2, 7, 1, 1),
        )

        readings = profile.parse_notification(FLUKE_MEAS_UUID, payload, "meter-37x", observed_at=observed_at)

        self.assertEqual(len(readings), 2)
        primary = readings[0]
        secondary = readings[1]
        self.assertEqual(primary.measurement_type, MeasurementType.VOLTAGE_DC)
        self.assertEqual(primary.value, 12.3)
        self.assertEqual(primary.metadata["channel_role"], "primary")
        self.assertEqual(primary.metadata["relative_mode"], "true")
        self.assertEqual(primary.metadata["phase_to_phase"], "true")
        self.assertEqual(secondary.measurement_type, MeasurementType.CURRENT_DC)
        self.assertEqual(secondary.value, 0.45)
        self.assertEqual(secondary.metadata["channel_role"], "secondary")
        self.assertIn("Clockwise", secondary.metadata["family_mode_badges"])

    def test_advanced_clamp_profile_omits_invalid_secondary_reading(self) -> None:
        profile = FlukeAdvancedClampFamilyProfile()
        payload = advanced_clamp_frame(
            advanced_clamp_reading_payload(
                counts=222,
                state=0,
                decimal_places=1,
                magnitude=0,
                sign=0,
                unit_code=1,
                function_code=87,
            ),
            advanced_clamp_reading_payload(
                counts=0,
                state=3,
                decimal_places=0,
                magnitude=0,
                sign=0,
                unit_code=3,
                function_code=87,
            ),
        )

        readings = profile.parse_notification(FLUKE_MEAS_UUID, payload, "meter-377")

        self.assertEqual(len(readings), 1)
        self.assertEqual(readings[0].measurement_type, MeasurementType.FIELDSENSE)
        self.assertEqual(readings[0].metadata["channel_role"], "primary")


if __name__ == "__main__":
    unittest.main()
