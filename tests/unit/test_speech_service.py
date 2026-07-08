from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from tests.unit._helpers import PACKAGES  # noqa: F401 - ensures sys.path setup

from fluke_app.speech_service import (
    EspeakBackend,
    MacSayBackend,
    NullSpeechBackend,
    SpeechConfig,
    SpeechMode,
    SpeechService,
    WindowsSapiBackend,
    pronounce_number,
    pronounce_unit,
    reading_to_speech_text,
    select_backend,
)
from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading

_BASE = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def _reading(
    value: float | None,
    *,
    at: datetime | None = None,
    unit: str = "V",
    measurement_type: MeasurementType = MeasurementType.VOLTAGE_DC,
    status: ReadingStatus = ReadingStatus.OK,
) -> Reading:
    return Reading(
        timestamp_utc=at or _BASE,
        value=value,
        unit=unit,
        measurement_type=measurement_type,
        status=status,
        display_text=f"{value} {unit}" if value is not None else "OL",
        source_device_id="dev-1",
    )


class _FakeBackend:
    def __init__(self, available: bool = True, name: str = "fake") -> None:
        self.name = name
        self._available = available
        self.spoken: list[str] = []

    def available(self) -> bool:
        return self._available

    def speak(self, text: str) -> None:
        self.spoken.append(text)


class PronounceUnitTests(unittest.TestCase):
    def test_volts_ac(self) -> None:
        self.assertEqual(pronounce_unit("V", MeasurementType.VOLTAGE_AC), "volts A C")

    def test_volts_dc(self) -> None:
        self.assertEqual(pronounce_unit("V", MeasurementType.VOLTAGE_DC), "volts D C")

    def test_milliamps(self) -> None:
        self.assertEqual(pronounce_unit("mA", MeasurementType.CURRENT_DC), "milliamps D C")

    def test_kilo_ohms(self) -> None:
        self.assertEqual(pronounce_unit("kOhm", MeasurementType.RESISTANCE), "kilo-ohms")

    def test_mega_ohms(self) -> None:
        self.assertEqual(pronounce_unit("MOhm", MeasurementType.RESISTANCE), "mega-ohms")

    def test_hertz(self) -> None:
        self.assertEqual(pronounce_unit("Hz", MeasurementType.FREQUENCY), "hertz")

    def test_microfarads(self) -> None:
        self.assertEqual(pronounce_unit("uF", MeasurementType.CAPACITANCE), "microfarads")

    def test_percent(self) -> None:
        self.assertEqual(pronounce_unit("%", MeasurementType.DUTY_CYCLE), "percent")

    def test_celsius(self) -> None:
        self.assertEqual(pronounce_unit("C", MeasurementType.TEMPERATURE), "degrees Celsius")

    def test_ac_dc_current(self) -> None:
        self.assertEqual(pronounce_unit("A", MeasurementType.CURRENT_AC_DC), "amps A C D C")

    def test_millivolts(self) -> None:
        self.assertEqual(pronounce_unit("mV", MeasurementType.VOLTAGE_DC), "millivolts D C")

    def test_algorithmic_fallback(self) -> None:
        # kHz not in explicit table order? It is, but test a prefix fallback path.
        self.assertEqual(pronounce_unit("kV", None), "kilovolts")

    def test_unknown_unit_passthrough(self) -> None:
        self.assertEqual(pronounce_unit("xyz", None), "xyz")


class PronounceNumberTests(unittest.TestCase):
    def test_decimal(self) -> None:
        self.assertEqual(pronounce_number(121.3), "121 point 3")

    def test_integer(self) -> None:
        self.assertEqual(pronounce_number(240), "240")

    def test_negative(self) -> None:
        self.assertEqual(pronounce_number(-12.5), "negative 12 point 5")

    def test_leading_zero_decimal(self) -> None:
        self.assertEqual(pronounce_number(0.05), "0 point 0 5")

    def test_none(self) -> None:
        self.assertEqual(pronounce_number(None), "")


class ReadingToSpeechTextTests(unittest.TestCase):
    def test_full_ac_voltage(self) -> None:
        reading = _reading(121.3, unit="V", measurement_type=MeasurementType.VOLTAGE_AC)
        self.assertEqual(reading_to_speech_text(reading), "121 point 3 volts A C")

    def test_current_dc(self) -> None:
        reading = _reading(2.5, unit="A", measurement_type=MeasurementType.CURRENT_DC)
        self.assertEqual(reading_to_speech_text(reading), "2 point 5 amps D C")

    def test_resistance(self) -> None:
        reading = _reading(4.7, unit="kOhm", measurement_type=MeasurementType.RESISTANCE)
        self.assertEqual(reading_to_speech_text(reading), "4 point 7 kilo-ohms")

    def test_over_range(self) -> None:
        reading = _reading(None, status=ReadingStatus.OVER_RANGE)
        self.assertEqual(reading_to_speech_text(reading), "over range")


class BackendSelectionTests(unittest.TestCase):
    def test_selects_first_available(self) -> None:
        first = _FakeBackend(available=False, name="a")
        second = _FakeBackend(available=True, name="b")
        third = _FakeBackend(available=True, name="c")
        chosen = select_backend([first, second, third])
        self.assertIs(chosen, second)

    def test_falls_back_to_null(self) -> None:
        chosen = select_backend([_FakeBackend(available=False)])
        self.assertIsInstance(chosen, NullSpeechBackend)

    def test_windows_backend_platform_gating(self) -> None:
        self.assertTrue(WindowsSapiBackend(platform="win32").available())
        self.assertFalse(WindowsSapiBackend(platform="linux").available())

    def test_mac_backend_requires_say(self) -> None:
        available = MacSayBackend(platform="darwin", _which=lambda name: "/usr/bin/say")
        missing = MacSayBackend(platform="darwin", _which=lambda name: None)
        wrong_platform = MacSayBackend(platform="linux", _which=lambda name: "/usr/bin/say")
        self.assertTrue(available.available())
        self.assertFalse(missing.available())
        self.assertFalse(wrong_platform.available())

    def test_espeak_backend_requires_binary(self) -> None:
        found = EspeakBackend(_which=lambda name: "/usr/bin/espeak" if name == "espeak" else None)
        missing = EspeakBackend(_which=lambda name: None)
        self.assertTrue(found.available())
        self.assertFalse(missing.available())

    def test_espeak_ng_fallback(self) -> None:
        backend = EspeakBackend(
            _which=lambda name: "/usr/bin/espeak-ng" if name == "espeak-ng" else None
        )
        self.assertTrue(backend.available())

    def test_windows_backend_escapes_and_runs(self) -> None:
        commands: list[list[str]] = []
        backend = WindowsSapiBackend(platform="win32", runner=lambda cmd: commands.append(list(cmd)))
        backend.speak("it's 5 volts")
        self.assertEqual(len(commands), 1)
        joined = " ".join(commands[0])
        self.assertIn("it''s 5 volts", joined)


class SpeechServiceModeTests(unittest.TestCase):
    def test_disabled_service_says_nothing(self) -> None:
        backend = _FakeBackend()
        service = SpeechService(SpeechConfig(enabled=False), backend=backend)
        self.assertIsNone(service.on_reading(_reading(120.0)))
        self.assertEqual(backend.spoken, [])

    def test_interval_mode(self) -> None:
        backend = _FakeBackend()
        service = SpeechService(
            SpeechConfig(enabled=True, mode=SpeechMode.INTERVAL, interval_seconds=5.0),
            backend=backend,
        )
        # First reading always speaks.
        self.assertIsNotNone(service.on_reading(_reading(120.0, at=_BASE)))
        # Too soon.
        self.assertIsNone(service.on_reading(_reading(121.0, at=_BASE + timedelta(seconds=2))))
        # After interval.
        self.assertIsNotNone(service.on_reading(_reading(122.0, at=_BASE + timedelta(seconds=6))))
        self.assertEqual(len(backend.spoken), 2)

    def test_on_change_mode(self) -> None:
        backend = _FakeBackend()
        service = SpeechService(
            SpeechConfig(enabled=True, mode=SpeechMode.ON_CHANGE, change_delta=1.0),
            backend=backend,
        )
        self.assertIsNotNone(service.on_reading(_reading(100.0)))
        self.assertIsNone(service.on_reading(_reading(100.5)))  # below delta
        self.assertIsNotNone(service.on_reading(_reading(102.0)))  # above delta

    def test_on_stable_mode(self) -> None:
        backend = _FakeBackend()
        service = SpeechService(
            SpeechConfig(
                enabled=True,
                mode=SpeechMode.ON_STABLE,
                stable_tolerance=0.02,
                stable_samples=3,
            ),
            backend=backend,
        )
        service.on_reading(_reading(100.0))
        service.on_reading(_reading(100.1))
        spoken = service.on_reading(_reading(100.2))  # 3rd stable sample -> announce
        self.assertIsNotNone(spoken)
        # Does not re-announce while still stable.
        self.assertIsNone(service.on_reading(_reading(100.15)))

    def test_on_alert_mode_skips_readings(self) -> None:
        backend = _FakeBackend()
        service = SpeechService(
            SpeechConfig(enabled=True, mode=SpeechMode.ON_ALERT),
            backend=backend,
        )
        self.assertIsNone(service.on_reading(_reading(120.0)))
        # But explicit alerts still speak.
        service.speak_alert("HIGH ALERT")
        self.assertEqual(backend.spoken, ["HIGH ALERT"])

    def test_speak_alert_respects_toggle(self) -> None:
        backend = _FakeBackend()
        service = SpeechService(
            SpeechConfig(enabled=True, speak_alerts=False),
            backend=backend,
        )
        service.speak_alert("HIGH ALERT")
        self.assertEqual(backend.spoken, [])

    def test_is_available_reflects_backend(self) -> None:
        self.assertFalse(SpeechService(backend=NullSpeechBackend()).is_available())
        self.assertTrue(SpeechService(backend=_FakeBackend()).is_available())


if __name__ == "__main__":
    unittest.main()
