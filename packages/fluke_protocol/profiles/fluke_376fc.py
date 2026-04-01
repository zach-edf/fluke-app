from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading
from fluke_protocol.profiles.base import DeviceProfile

FLUKE_MEAS_UUID = "b6982901-7562-11e2-b50d-00163e46f8fe"
FLUKE_STATUS_UUID = "b698290f-7562-11e2-b50d-00163e46f8fe"
# Service UUID present in the BLE advertisement packet (distinct from the GATT
# characteristic UUIDs above, which are only visible after connecting).
FLUKE_ADV_SERVICE_UUID = "b6981800-7562-11e2-b50d-00163e46f8fe"

_VALUE_UNIT_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*([^\d\s].*)?$")
_VALUE_UNIT_ALT_RE = re.compile(r"^([+-]?\d+(?:\.\d+)?)\s*L\s*([^\d\s].*)?$", re.IGNORECASE)
_OVERLOAD_RE = re.compile(r"^[0O]L\s*(.*)$")

MODE_LABELS: dict[str, str] = {
    "ac": "AC",
    "dc": "DC",
    "acdc": "AC+DC",
    "inrush": "Inrush",
    "acin": "Inrush (AC)",
    "dcin": "Inrush (DC)",
    "vfd": "VFD (Low-Pass)",
    "hz": "Frequency",
}

MODE_ALIASES: dict[str, str] = {
    "ac+dc": "acdc",
    "ac/dc": "acdc",
    "dcac": "acdc",
    "frq": "hz",
    "freq": "hz",
    "acinrush": "acin",
    "dcinrush": "dcin",
    "in": "inrush",
    "lpf": "vfd",
    "lowpass": "vfd",
}

UNIT_NORMALIZATION: dict[str, tuple[str, str]] = {
    "v": ("V", "voltage"),
    "mv": ("mV", "voltage"),
    "a": ("A", "current"),
    "ma": ("mA", "current"),
    "ua": ("uA", "current"),
    "hz": ("Hz", "frequency"),
    "h": ("Hz", "frequency"),
    "ohm": ("ohm", "resistance"),
    "ko": ("kOhm", "resistance"),
    "koh": ("kOhm", "resistance"),
    "kohm": ("kOhm", "resistance"),
    "komega": ("kOhm", "resistance"),
    "mohm": ("MOhm", "resistance"),
    "moh": ("MOhm", "resistance"),
    "uf": ("uF", "capacitance"),
    "nf": ("nF", "capacitance"),
    "pf": ("pF", "capacitance"),
    "f": ("F", "capacitance"),
    "%": ("%", "duty_cycle"),
    "c": ("C", "temperature"),
    "fdeg": ("F", "temperature"),
}

FUNCTION_LABELS: dict[str, str] = {
    "ac_voltage": "AC Voltage",
    "dc_voltage": "DC Voltage",
    "dc_millivolts": "DC mV",
    "ac_current": "AC Current",
    "dc_current": "DC Current",
    "acdc_current": "AC+DC Current",
    "frequency": "Frequency",
    "resistance_continuity": "Resistance / Continuity",
    "capacitance": "Capacitance",
    "duty_cycle": "Duty Cycle",
    "temperature": "Temperature",
    "inrush_current": "Inrush Current",
    "unknown": "Unknown",
}

FUNCTION_TO_MEASUREMENT: dict[str, MeasurementType] = {
    "ac_voltage": MeasurementType.VOLTAGE_AC,
    "dc_voltage": MeasurementType.VOLTAGE_DC,
    "dc_millivolts": MeasurementType.VOLTAGE_DC,
    "ac_current": MeasurementType.CURRENT_AC,
    "dc_current": MeasurementType.CURRENT_DC,
    "acdc_current": MeasurementType.CURRENT_AC_DC,
    "frequency": MeasurementType.FREQUENCY,
    "resistance_continuity": MeasurementType.RESISTANCE,
    "capacitance": MeasurementType.CAPACITANCE,
    "duty_cycle": MeasurementType.DUTY_CYCLE,
    "temperature": MeasurementType.TEMPERATURE,
    "inrush_current": MeasurementType.CURRENT_INRUSH,
    "unknown": MeasurementType.UNKNOWN,
}


@dataclass(frozen=True, slots=True)
class ModeDecode:
    mode_raw: str
    mode_token: str
    mode_label: str
    known_mode: bool
    unit_raw: str
    unit_norm: str
    unit_family: str
    known_unit: bool
    function_key: str
    function_label: str


class Fluke376FCProfile(DeviceProfile):
    profile_id = "fluke_376fc"
    model_name = "Fluke 376 FC"

    def __init__(self) -> None:
        self._latest_status_tenths: dict[str, float | None] = {}

    def matches(self, advertisement_name: str | None, metadata: dict[str, object]) -> bool:
        candidates = [
            advertisement_name or "",
            str(metadata.get("advertisement_name") or ""),
        ]
        for candidate in candidates:
            token = candidate.lower().replace(" ", "")
            if "376fc" in token or ("fluke" in token and "376" in token):
                return True
        # Fallback: match by the service UUID the 376 FC includes in its advertisement
        # packet. This is distinct from the GATT characteristic UUIDs (MEAS/STATUS),
        # which only appear after connecting. On Windows the WinRT BLE backend
        # sometimes returns None for both device.name and adv.local_name for unpaired
        # devices, so this UUID-based path provides a reliable secondary match.
        service_uuids = metadata.get("service_uuids") or []
        if isinstance(service_uuids, list):
            if FLUKE_ADV_SERVICE_UUID.lower() in {u.lower() for u in service_uuids}:
                return True
        return False

    def capabilities(self) -> list[str]:
        return [
            "live_reading",
            "stream_notifications",
            "dc_voltage",
            "ac_voltage",
            "dc_current",
            "ac_current",
            "inrush_current",
            "frequency",
            "capacitance",
            "resistance",
        ]

    def notification_characteristics(self) -> list[str]:
        return [FLUKE_MEAS_UUID, FLUKE_STATUS_UUID]

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        observed_at = observed_at or datetime.now(timezone.utc)
        char_uuid = characteristic_uuid.lower()

        if char_uuid == FLUKE_STATUS_UUID:
            self._latest_status_tenths[device_id] = _status_tenths_from_payload(payload)
            return []

        if char_uuid != FLUKE_MEAS_UUID:
            return []

        primary, value_text, unit_raw, mode_raw = _decode_fluke_measurement(payload)
        decode = _classify_mode(unit_raw, mode_raw)
        numeric_value = _parse_float(value_text)

        if numeric_value is None and primary.startswith("-"):
            cached_value = self._latest_status_tenths.get(device_id)
            if cached_value not in {None, 0.0}:
                numeric_value = cached_value

        reading = Reading(
            timestamp_utc=observed_at,
            value=numeric_value,
            unit=decode.unit_norm or unit_raw,
            measurement_type=FUNCTION_TO_MEASUREMENT.get(decode.function_key, MeasurementType.UNKNOWN),
            status=_reading_status(primary, numeric_value),
            display_text=primary or "",
            source_device_id=device_id,
            mode=decode.mode_token,
            raw_payload=payload,
            metadata={
                "mode_label": decode.mode_label,
                "mode_raw": decode.mode_raw,
                "unit_family": decode.unit_family,
                "function_key": decode.function_key,
                "function_label": decode.function_label,
                "known_mode": str(decode.known_mode).lower(),
                "known_unit": str(decode.known_unit).lower(),
            },
        )
        return [reading]

    def reset_device(self, device_id: str) -> None:
        self._latest_status_tenths.pop(device_id, None)


def _parse_float(text: str) -> float | None:
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _decode_fluke_measurement(payload: bytes) -> tuple[str, str, str, str]:
    if len(payload) < 17:
        return "", "", "", ""

    primary = payload[1:11].decode("ascii", errors="ignore").replace("\x00", "")
    primary = re.sub(r"\s+", " ", primary).strip()
    mode = payload[12:17].decode("ascii", errors="ignore").replace("\x00", "")
    mode = mode.strip().lower()
    value = ""
    unit = ""

    overload = _OVERLOAD_RE.match(primary)
    if overload:
        unit = overload.group(1).strip()
        primary = f"OL {unit}".strip()
        return primary, value, unit, mode

    match = _VALUE_UNIT_RE.match(primary) or _VALUE_UNIT_ALT_RE.match(primary)
    if match:
        value = (match.group(1) or "").strip()
        unit = (match.group(2) or "").strip()

    return primary, value, unit, mode


def _decode_fluke_measurement_hex(hex_payload: str) -> tuple[str, str, str, str]:
    try:
        payload = bytes.fromhex(hex_payload)
    except ValueError:
        return "", "", "", ""
    return _decode_fluke_measurement(payload)


def _status_tenths_from_hex(hex_payload: str) -> float | None:
    parts = hex_payload.split()
    if not parts:
        return None
    try:
        return int(parts[0], 16) / 10.0
    except ValueError:
        return None


def _status_tenths_from_payload(payload: bytes) -> float | None:
    if not payload:
        return None
    return payload[0] / 10.0


def _normalize_mode_token(raw_mode: str) -> tuple[str, str, bool]:
    raw = (raw_mode or "").replace("\x00", "").strip().lower()
    if not raw:
        return "", "", False
    token = raw.replace("\x00", "")
    token = token.replace(" ", "")
    token = token.replace("_", "").replace("-", "")
    token = token.rstrip("*")
    token = re.sub(r"[^a-z+]", "", token)
    token = MODE_ALIASES.get(token, token)
    if token in MODE_LABELS:
        return token, MODE_LABELS[token], True
    return token, f"Unknown ({raw})", False


def _normalize_unit_token(raw_unit: str) -> tuple[str, str, bool]:
    raw = (raw_unit or "").replace("\x00", "").strip()
    if not raw:
        return "", "unknown", False

    token = raw.lower().replace("\x00", "")
    token = token.replace(" ", "")
    token = token.replace("Ï‰", "ohm").replace("Î©", "ohm").replace("â„¦", "ohm")
    token = token.replace("Î¼", "u")
    if token.startswith("l") and len(token) > 1:
        maybe = token[1:]
        if maybe in UNIT_NORMALIZATION:
            token = maybe
    if token in UNIT_NORMALIZATION:
        unit_norm, family = UNIT_NORMALIZATION[token]
        return unit_norm, family, True
    return raw, "unknown", False


def _infer_function(mode_token: str, unit_norm: str, unit_family: str) -> tuple[str, str]:
    if mode_token in {"inrush", "acin", "dcin"}:
        return "inrush_current", FUNCTION_LABELS["inrush_current"]

    if unit_family == "frequency":
        return "frequency", FUNCTION_LABELS["frequency"]
    if unit_family == "resistance":
        return "resistance_continuity", FUNCTION_LABELS["resistance_continuity"]
    if unit_family == "capacitance":
        return "capacitance", FUNCTION_LABELS["capacitance"]
    if unit_family == "duty_cycle":
        return "duty_cycle", FUNCTION_LABELS["duty_cycle"]
    if unit_family == "temperature":
        return "temperature", FUNCTION_LABELS["temperature"]

    if unit_norm == "V":
        if mode_token == "ac":
            return "ac_voltage", FUNCTION_LABELS["ac_voltage"]
        if mode_token == "dc":
            return "dc_voltage", FUNCTION_LABELS["dc_voltage"]
    if unit_norm == "mV":
        return "dc_millivolts", FUNCTION_LABELS["dc_millivolts"]
    if unit_norm == "A":
        if mode_token == "ac":
            return "ac_current", FUNCTION_LABELS["ac_current"]
        if mode_token == "dc":
            return "dc_current", FUNCTION_LABELS["dc_current"]
        if mode_token == "acdc":
            return "acdc_current", FUNCTION_LABELS["acdc_current"]
    if unit_norm in {"mA", "uA"}:
        return "dc_current", FUNCTION_LABELS["dc_current"]

    return "unknown", FUNCTION_LABELS["unknown"]


def _classify_mode(unit_raw: str, mode_raw: str) -> ModeDecode:
    mode_token, mode_label, known_mode = _normalize_mode_token(mode_raw)
    unit_norm, unit_family, known_unit = _normalize_unit_token(unit_raw)
    function_key, function_label = _infer_function(mode_token, unit_norm, unit_family)
    return ModeDecode(
        mode_raw=(mode_raw or "").strip(),
        mode_token=mode_token,
        mode_label=mode_label,
        known_mode=known_mode,
        unit_raw=(unit_raw or "").strip(),
        unit_norm=unit_norm,
        unit_family=unit_family,
        known_unit=known_unit,
        function_key=function_key,
        function_label=function_label,
    )


def _reading_status(display_text: str, numeric_value: float | None) -> ReadingStatus:
    display = display_text.strip().upper()
    if display.startswith("OL"):
        return ReadingStatus.OVER_RANGE
    if numeric_value is None:
        return ReadingStatus.INVALID
    return ReadingStatus.OK
