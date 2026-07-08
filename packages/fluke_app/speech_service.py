"""Spoken-reading (text-to-speech) shared service.

This module keeps three concerns separate so each is independently testable:

1. A pure ``reading_to_speech_text`` formatter that turns a normalized
   ``Reading`` (e.g. display ``121.3 V`` AC) into a pronounceable string
   (``121 point 3 volts A C``). Unit pronunciation lives in ``pronounce_unit``.
2. A tiny platform-native TTS *backend* abstraction (Windows SAPI via
   PowerShell, macOS ``say``, Linux ``espeak``/``espeak-ng``, or ``pyttsx3``)
   with a graceful "TTS unavailable" ``NullSpeechBackend`` fallback.
3. ``SpeechService``, a stateful policy object that decides *when* to announce a
   reading based on the selected mode (interval / on-stable / on-change / alert).

No audio is produced during tests: backends are selected via injectable
candidate lists and every speak call is routed through an injectable runner.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Protocol, runtime_checkable

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading


# ---------------------------------------------------------------------------
# Speech-text formatting
# ---------------------------------------------------------------------------

# Authoritative pronunciation for the units the in-tree profiles emit. Keeping
# an explicit table (rather than purely algorithmic prefix expansion) lets us
# honor the small spelling quirks people expect when hearing them read aloud
# ("milliamps" but "kilo-ohms").
UNIT_SPEECH: dict[str, str] = {
    "": "",
    "V": "volts",
    "mV": "millivolts",
    "kV": "kilovolts",
    "A": "amps",
    "mA": "milliamps",
    "uA": "microamps",
    "µA": "microamps",
    "kA": "kiloamps",
    "ohm": "ohms",
    "Ohm": "ohms",
    "Ω": "ohms",
    "kohm": "kilo-ohms",
    "kOhm": "kilo-ohms",
    "Mohm": "mega-ohms",
    "MOhm": "mega-ohms",
    "Hz": "hertz",
    "kHz": "kilohertz",
    "MHz": "megahertz",
    "F": "farads",
    "mF": "millifarads",
    "uF": "microfarads",
    "µF": "microfarads",
    "nF": "nanofarads",
    "pF": "picofarads",
    "%": "percent",
    "C": "degrees Celsius",
    "°C": "degrees Celsius",
    "s": "seconds",
    "ms": "milliseconds",
    "VA": "volt-amps",
    "W": "watts",
    "kW": "kilowatts",
}

_SI_PREFIXES: dict[str, str] = {
    "k": "kilo",
    "M": "mega",
    "G": "giga",
    "m": "milli",
    "u": "micro",
    "µ": "micro",
    "n": "nano",
    "p": "pico",
}

_BASE_UNITS: dict[str, str] = {
    "V": "volts",
    "A": "amps",
    "Hz": "hertz",
    "F": "farads",
    "W": "watts",
    "ohm": "ohms",
    "Ohm": "ohms",
}


def pronounce_unit(unit: str, measurement_type: MeasurementType | None = None) -> str:
    """Return a pronounceable spelling of ``unit`` plus any AC/DC qualifier."""
    base = _pronounce_unit_base((unit or "").strip())
    qualifier = _ac_dc_qualifier(measurement_type)
    if base and qualifier:
        return f"{base} {qualifier}"
    return base or qualifier


def _pronounce_unit_base(unit: str) -> str:
    if unit in UNIT_SPEECH:
        return UNIT_SPEECH[unit]
    # Algorithmic fallback: SI prefix + known base unit.
    if len(unit) >= 2 and unit[0] in _SI_PREFIXES:
        remainder = unit[1:]
        if remainder in _BASE_UNITS:
            return f"{_SI_PREFIXES[unit[0]]}{_BASE_UNITS[remainder]}"
    # Last resort: read the raw token so the user still hears *something*.
    return unit


def _ac_dc_qualifier(measurement_type: MeasurementType | None) -> str:
    if measurement_type is None:
        return ""
    name = measurement_type.value
    if name.endswith("_ac_dc") or "ac_dc" in name:
        return "A C D C"
    if name.endswith("_ac") or "_ac" in name:
        return "A C"
    if name.endswith("_dc") or "_dc" in name:
        return "D C"
    return ""


def pronounce_number(value: float | None) -> str:
    """Turn a numeric value into a spoken string (``-12.3`` -> ``negative 12 point 3``)."""
    if value is None:
        return ""
    if value != value:  # NaN
        return ""
    if value < 0:
        return f"negative {pronounce_number(-value)}"

    text = f"{value:.6g}"
    if "e" in text or "E" in text:  # avoid scientific notation in speech
        text = f"{value:.6f}".rstrip("0").rstrip(".")
    if "." not in text:
        return text
    integer_part, _, decimal_part = text.partition(".")
    integer_part = integer_part or "0"
    spoken_decimals = " ".join(decimal_part)
    return f"{integer_part} point {spoken_decimals}".strip()


_STATUS_SPEECH: dict[ReadingStatus, str] = {
    ReadingStatus.OVER_RANGE: "over range",
    ReadingStatus.UNDER_RANGE: "under range",
    ReadingStatus.NO_SIGNAL: "no signal",
    ReadingStatus.INVALID: "invalid reading",
}


def reading_to_speech_text(reading: Reading) -> str:
    """Full spoken representation of a reading, value + unit (+ AC/DC)."""
    if reading.value is None:
        status_text = _STATUS_SPEECH.get(reading.status)
        if status_text:
            return status_text
        return reading.display_text or "no reading"
    number = pronounce_number(reading.value)
    unit = pronounce_unit(reading.unit, reading.measurement_type)
    return f"{number} {unit}".strip()


# ---------------------------------------------------------------------------
# TTS backends
# ---------------------------------------------------------------------------

Runner = Callable[[Sequence[str]], None]


def _default_runner(command: Sequence[str]) -> None:
    """Fire-and-forget subprocess launch so speaking never blocks the caller."""
    subprocess.Popen(  # noqa: S603 - command is built from fixed argv, no shell
        list(command),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
    )


@runtime_checkable
class SpeechBackend(Protocol):
    name: str

    def available(self) -> bool:
        ...

    def speak(self, text: str) -> None:
        ...


@dataclass
class NullSpeechBackend:
    """Fallback backend used when no platform TTS engine is usable."""

    name: str = "unavailable"

    def available(self) -> bool:
        return False

    def speak(self, text: str) -> None:  # pragma: no cover - intentional no-op
        return None


@dataclass
class WindowsSapiBackend:
    name: str = "windows-sapi"
    platform: str = sys.platform
    runner: Runner = _default_runner

    def available(self) -> bool:
        return self.platform.startswith("win")

    def speak(self, text: str) -> None:
        script = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{_ps_escape(text)}')"
        )
        self.runner(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


@dataclass
class MacSayBackend:
    name: str = "macos-say"
    platform: str = sys.platform
    runner: Runner = _default_runner
    _which: Callable[[str], str | None] = field(default=shutil.which, repr=False)

    def available(self) -> bool:
        return self.platform == "darwin" and self._which("say") is not None

    def speak(self, text: str) -> None:
        self.runner(["say", text])


@dataclass
class EspeakBackend:
    name: str = "espeak"
    runner: Runner = _default_runner
    _which: Callable[[str], str | None] = field(default=shutil.which, repr=False)

    def _binary(self) -> str | None:
        return self._which("espeak") or self._which("espeak-ng")

    def available(self) -> bool:
        return self._binary() is not None

    def speak(self, text: str) -> None:
        binary = self._binary()
        if binary is None:
            return
        self.runner([binary, text])


@dataclass
class Pyttsx3Backend:
    """Cross-platform backend when the optional ``pyttsx3`` package is installed."""

    name: str = "pyttsx3"

    def available(self) -> bool:
        try:
            import pyttsx3  # noqa: F401
        except Exception:
            return False
        return True

    def speak(self, text: str) -> None:  # pragma: no cover - requires pyttsx3 + audio
        try:
            import pyttsx3

            engine = pyttsx3.init()
            engine.say(text)
            engine.runAndWait()
        except Exception:
            return None


def _ps_escape(text: str) -> str:
    # Single-quote escaping for PowerShell string literals.
    return text.replace("'", "''")


def default_backends() -> list[SpeechBackend]:
    """Candidate backends in preference order for the current platform."""
    return [
        WindowsSapiBackend(),
        MacSayBackend(),
        EspeakBackend(),
        Pyttsx3Backend(),
    ]


def select_backend(candidates: Sequence[SpeechBackend] | None = None) -> SpeechBackend:
    """Return the first available backend, or the null fallback."""
    for backend in candidates if candidates is not None else default_backends():
        try:
            if backend.available():
                return backend
        except Exception:
            continue
    return NullSpeechBackend()


# ---------------------------------------------------------------------------
# Speech service (when-to-speak policy)
# ---------------------------------------------------------------------------


class SpeechMode(str, Enum):
    INTERVAL = "interval"
    ON_STABLE = "on_stable"
    ON_CHANGE = "on_change"
    ON_ALERT = "on_alert"


@dataclass(frozen=True, slots=True)
class SpeechConfig:
    enabled: bool = False
    mode: SpeechMode = SpeechMode.INTERVAL
    interval_seconds: float = 10.0
    # For ON_CHANGE: minimum absolute value delta to trigger an announcement.
    change_delta: float = 1.0
    # For ON_STABLE: relative tolerance and consecutive-sample count.
    stable_tolerance: float = 0.02
    stable_samples: int = 3
    # Also announce alert transitions regardless of mode.
    speak_alerts: bool = True


class SpeechService:
    """Decides when to speak readings and routes text to a TTS backend."""

    def __init__(
        self,
        config: SpeechConfig | None = None,
        backend: SpeechBackend | None = None,
    ) -> None:
        self._config = config or SpeechConfig()
        self._backend = backend or select_backend()
        self._last_spoken_at: datetime | None = None
        self._last_spoken_value: float | None = None
        self._stable_run = 0
        self._stable_announced = False
        self._stable_anchor: float | None = None

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def is_available(self) -> bool:
        return not isinstance(self._backend, NullSpeechBackend)

    @property
    def config(self) -> SpeechConfig:
        return self._config

    def set_config(self, config: SpeechConfig) -> None:
        self._config = config
        self.reset()

    def set_backend(self, backend: SpeechBackend) -> None:
        self._backend = backend

    def reset(self) -> None:
        self._last_spoken_at = None
        self._last_spoken_value = None
        self._stable_run = 0
        self._stable_announced = False
        self._stable_anchor = None

    def announce(self, text: str) -> str:
        """Speak arbitrary text immediately (used for alerts / status)."""
        if not self._config.enabled or not text:
            return ""
        self._backend.speak(text)
        return text

    def speak_alert(self, message: str) -> str:
        if not self._config.enabled or not self._config.speak_alerts:
            return ""
        return self.announce(message)

    def on_reading(self, reading: Reading) -> str | None:
        """Evaluate a reading and speak it if the mode's criteria are met.

        Returns the spoken text (also useful for tests) or ``None``.
        """
        if not self._config.enabled:
            return None
        if not self._should_speak(reading):
            return None
        text = reading_to_speech_text(reading)
        if not text:
            return None
        self._backend.speak(text)
        self._last_spoken_at = reading.timestamp_utc or datetime.now(timezone.utc)
        self._last_spoken_value = reading.value
        return text

    def _should_speak(self, reading: Reading) -> bool:
        mode = self._config.mode
        if mode is SpeechMode.ON_ALERT:
            return False  # alerts are announced via speak_alert()
        if mode is SpeechMode.INTERVAL:
            return self._interval_due(reading)
        if mode is SpeechMode.ON_CHANGE:
            return self._changed_enough(reading)
        if mode is SpeechMode.ON_STABLE:
            return self._became_stable(reading)
        return False

    def _interval_due(self, reading: Reading) -> bool:
        now = reading.timestamp_utc or datetime.now(timezone.utc)
        if self._last_spoken_at is None:
            return True
        return (now - self._last_spoken_at).total_seconds() >= self._config.interval_seconds

    def _changed_enough(self, reading: Reading) -> bool:
        if reading.value is None:
            return False
        if self._last_spoken_value is None:
            return True
        return abs(reading.value - self._last_spoken_value) >= self._config.change_delta

    def _became_stable(self, reading: Reading) -> bool:
        value = reading.value
        if value is None:
            self._stable_run = 0
            self._stable_announced = False
            self._stable_anchor = None
            return False
        anchor = self._stable_anchor
        tolerance = abs(anchor) * self._config.stable_tolerance if anchor else self._config.stable_tolerance
        if anchor is not None and abs(value - anchor) <= tolerance:
            self._stable_run += 1
        else:
            self._stable_anchor = value
            self._stable_run = 1
            self._stable_announced = False
        if self._stable_run >= self._config.stable_samples and not self._stable_announced:
            self._stable_announced = True
            return True
        return False
