from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone

from fluke_core.enums import MeasurementType, ReadingStatus
from fluke_core.models.reading import Reading
from fluke_protocol.profiles.base import DeviceFamilyRuntime, DeviceMatch, DeviceProfile, DeviceServiceSet

FLUKE_MEAS_UUID = "b6982901-7562-11e2-b50d-00163e46f8fe"
FLUKE_STATUS_UUID = "b698290f-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_SERVICE_UUID = "b6981802-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_STATUS_UUID = "b6982906-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_CONFIG_UUID = "b6982907-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_CONTROL_POINT_UUID = "b6982908-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_CAPACITY_UUID = "b698290d-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_BUFFER_UUID = "b6982917-7562-11e2-b50d-00163e46f8fe"
# Service UUID present in the BLE advertisement packet (distinct from the GATT
# characteristic UUIDs above, which are only visible after connecting).
FLUKE_ADV_SERVICE_UUID = "b6981800-7562-11e2-b50d-00163e46f8fe"
FLUKE_LOGGING_BYTES_PER_BLOCK = 18
FLUKE_LOGGING_HEADER_TAG = 0x01
FLUKE_LOGGING_DETAIL_TAG = 0x20
FLUKE_LOGGING_DUAL_READING_DETAIL_TAG = 0x40

FLUKE_LOGGING_STATE_LABELS: dict[int, str] = {
    0: "idle",
    1: "logging",
    2: "logging_not_supported",
    3: "erasing",
    4: "locked_for_download",
}

FLUKE_LOGGING_CONTROL_POINT_CODES: dict[str, int] = {
    "stop_logging_session": 0x80,
    "start_logging_session": 0x81,
    "erase_logged_data": 0x82,
    "lock_for_download": 0x83,
    "download_request": 0x84,
    "cancel_download_request": 0x85,
    "unlock": 0x86,
    "capture": 0x87,
}

FLUKE_LOGGING_CONTROL_RESPONSE_LABELS: dict[int, str] = {
    0: "idle",
    1: "command_rejected",
    2: "download_active",
    3: "download_complete",
    5: "canceled",
    6: "failed_to_start",
}

FLUKE_LOGGING_READING_STATE_LABELS: dict[int, str] = {
    0: "normal",
    1: "invalid",
    2: "open_tc",
    3: "over_limit",
    4: "over_limit_negative",
}

FLUKE_LOGGING_MAGNITUDE_EXPONENTS: dict[int, int] = {
    0: 0,
    1: 9,
    2: 6,
    3: 3,
    4: -3,
    5: -6,
    6: -9,
    7: -12,
    9: 15,
    10: 12,
}

FLUKE_LOGGING_UNIT_LABELS: dict[int, str] = {
    0: "none",
    1: "V AC",
    2: "V DC",
    3: "A AC",
    4: "A DC",
    5: "Hz",
    6: "ohm",
    7: "farad",
    8: "continuity",
    9: "deg F",
    10: "deg C",
    11: "%",
    12: "dBm",
    13: "S",
    14: "V AC+DC",
    15: "A AC+DC",
}

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


@dataclass(frozen=True, slots=True)
class Fluke376FCLoggingConfig:
    interval_seconds: int
    duration_seconds: int

    @classmethod
    def from_payload(cls, payload: bytes) -> "Fluke376FCLoggingConfig":
        if len(payload) != 8:
            raise ValueError(f"Expected 8-byte logging config payload, got {len(payload)} byte(s).")
        interval_seconds = int.from_bytes(payload[0:4], byteorder="little", signed=False)
        duration_seconds = int.from_bytes(payload[4:8], byteorder="little", signed=False)
        return cls(
            interval_seconds=interval_seconds,
            duration_seconds=duration_seconds,
        )

    def to_payload(self) -> bytes:
        if self.interval_seconds < 0:
            raise ValueError("interval_seconds must be non-negative.")
        if self.duration_seconds < 0:
            raise ValueError("duration_seconds must be non-negative.")
        if self.interval_seconds > 0xFFFFFFFF:
            raise ValueError("interval_seconds exceeds 32-bit storage.")
        if self.duration_seconds > 0xFFFFFFFF:
            raise ValueError("duration_seconds exceeds 32-bit storage.")
        return (
            int(self.interval_seconds).to_bytes(4, byteorder="little", signed=False)
            + int(self.duration_seconds).to_bytes(4, byteorder="little", signed=False)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "interval_seconds": self.interval_seconds,
            "duration_seconds": self.duration_seconds,
            "payload_hex": self.to_payload().hex(" "),
        }


@dataclass(frozen=True, slots=True)
class Fluke376FCLoggingStatus:
    state_code: int
    bytes_logged: int
    blocks_logged: int

    @classmethod
    def from_payload(cls, payload: bytes) -> "Fluke376FCLoggingStatus":
        if len(payload) != 9:
            raise ValueError(f"Expected 9-byte logging status payload, got {len(payload)} byte(s).")
        return cls(
            state_code=payload[0],
            bytes_logged=int.from_bytes(payload[1:5], byteorder="little", signed=False),
            blocks_logged=int.from_bytes(payload[5:9], byteorder="little", signed=False),
        )

    @property
    def state_label(self) -> str:
        return FLUKE_LOGGING_STATE_LABELS.get(self.state_code, "unknown")

    def as_dict(self) -> dict[str, object]:
        return {
            "state_code": self.state_code,
            "state_label": self.state_label,
            "bytes_logged": self.bytes_logged,
            "blocks_logged": self.blocks_logged,
            "payload_hex": self.to_payload().hex(" "),
        }

    def to_payload(self) -> bytes:
        if self.state_code < 0 or self.state_code > 0xFF:
            raise ValueError("state_code must fit in a single byte.")
        if self.bytes_logged < 0:
            raise ValueError("bytes_logged must be non-negative.")
        if self.blocks_logged < 0:
            raise ValueError("blocks_logged must be non-negative.")
        return (
            bytes([self.state_code])
            + int(self.bytes_logged).to_bytes(4, byteorder="little", signed=False)
            + int(self.blocks_logged).to_bytes(4, byteorder="little", signed=False)
        )


@dataclass(frozen=True, slots=True)
class Fluke376FCLoggingUnitDescriptor:
    unit_code: int
    unit_label: str
    unit: str
    measurement_type: MeasurementType
    mode: str = ""
    unit_family: str = "unknown"
    function_key: str = "unknown"
    function_label: str = FUNCTION_LABELS["unknown"]


_LOGGING_UNIT_DESCRIPTOR_MAP: dict[int, Fluke376FCLoggingUnitDescriptor] = {
    1: Fluke376FCLoggingUnitDescriptor(
        unit_code=1,
        unit_label="V AC",
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_AC,
        mode="ac",
        unit_family="voltage",
        function_key="ac_voltage",
        function_label=FUNCTION_LABELS["ac_voltage"],
    ),
    2: Fluke376FCLoggingUnitDescriptor(
        unit_code=2,
        unit_label="V DC",
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_DC,
        mode="dc",
        unit_family="voltage",
        function_key="dc_voltage",
        function_label=FUNCTION_LABELS["dc_voltage"],
    ),
    3: Fluke376FCLoggingUnitDescriptor(
        unit_code=3,
        unit_label="A AC",
        unit="A",
        measurement_type=MeasurementType.CURRENT_AC,
        mode="ac",
        unit_family="current",
        function_key="ac_current",
        function_label=FUNCTION_LABELS["ac_current"],
    ),
    4: Fluke376FCLoggingUnitDescriptor(
        unit_code=4,
        unit_label="A DC",
        unit="A",
        measurement_type=MeasurementType.CURRENT_DC,
        mode="dc",
        unit_family="current",
        function_key="dc_current",
        function_label=FUNCTION_LABELS["dc_current"],
    ),
    5: Fluke376FCLoggingUnitDescriptor(
        unit_code=5,
        unit_label="Hz",
        unit="Hz",
        measurement_type=MeasurementType.FREQUENCY,
        unit_family="frequency",
        function_key="frequency",
        function_label=FUNCTION_LABELS["frequency"],
    ),
    6: Fluke376FCLoggingUnitDescriptor(
        unit_code=6,
        unit_label="ohm",
        unit="ohm",
        measurement_type=MeasurementType.RESISTANCE,
        unit_family="resistance",
        function_key="resistance_continuity",
        function_label=FUNCTION_LABELS["resistance_continuity"],
    ),
    7: Fluke376FCLoggingUnitDescriptor(
        unit_code=7,
        unit_label="farad",
        unit="F",
        measurement_type=MeasurementType.CAPACITANCE,
        unit_family="capacitance",
        function_key="capacitance",
        function_label=FUNCTION_LABELS["capacitance"],
    ),
    8: Fluke376FCLoggingUnitDescriptor(
        unit_code=8,
        unit_label="continuity",
        unit="ohm",
        measurement_type=MeasurementType.CONTINUITY,
        unit_family="resistance",
        function_key="resistance_continuity",
        function_label=FUNCTION_LABELS["resistance_continuity"],
    ),
    9: Fluke376FCLoggingUnitDescriptor(
        unit_code=9,
        unit_label="deg F",
        unit="F",
        measurement_type=MeasurementType.TEMPERATURE,
        unit_family="temperature",
        function_key="temperature",
        function_label=FUNCTION_LABELS["temperature"],
    ),
    10: Fluke376FCLoggingUnitDescriptor(
        unit_code=10,
        unit_label="deg C",
        unit="C",
        measurement_type=MeasurementType.TEMPERATURE,
        unit_family="temperature",
        function_key="temperature",
        function_label=FUNCTION_LABELS["temperature"],
    ),
    11: Fluke376FCLoggingUnitDescriptor(
        unit_code=11,
        unit_label="%",
        unit="%",
        measurement_type=MeasurementType.DUTY_CYCLE,
        unit_family="duty_cycle",
        function_key="duty_cycle",
        function_label=FUNCTION_LABELS["duty_cycle"],
    ),
    14: Fluke376FCLoggingUnitDescriptor(
        unit_code=14,
        unit_label="V AC+DC",
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_AC_DC,
        mode="acdc",
        unit_family="voltage",
    ),
    15: Fluke376FCLoggingUnitDescriptor(
        unit_code=15,
        unit_label="A AC+DC",
        unit="A",
        measurement_type=MeasurementType.CURRENT_AC_DC,
        mode="acdc",
        unit_family="current",
        function_key="acdc_current",
        function_label=FUNCTION_LABELS["acdc_current"],
    ),
}


def describe_logging_unit_code(unit_code: int) -> Fluke376FCLoggingUnitDescriptor:
    if unit_code in _LOGGING_UNIT_DESCRIPTOR_MAP:
        return _LOGGING_UNIT_DESCRIPTOR_MAP[unit_code]
    return Fluke376FCLoggingUnitDescriptor(
        unit_code=unit_code,
        unit_label=FLUKE_LOGGING_UNIT_LABELS.get(unit_code, "unknown"),
        unit="",
        measurement_type=MeasurementType.UNKNOWN,
    )


def logging_state_code_to_reading_status(state_code: int) -> ReadingStatus:
    if state_code == 0:
        return ReadingStatus.OK
    if state_code == 1:
        return ReadingStatus.INVALID
    if state_code == 2:
        return ReadingStatus.NO_SIGNAL
    if state_code in {3, 4}:
        return ReadingStatus.OVER_RANGE
    return ReadingStatus.INVALID


def decode_logging_download_payload(payload: bytes) -> list[dict[str, object]]:
    if len(payload) % FLUKE_LOGGING_BYTES_PER_BLOCK != 0:
        raise ValueError(
            "Logging download payload length must be a multiple of "
            f"{FLUKE_LOGGING_BYTES_PER_BLOCK} byte blocks."
        )

    sessions: list[dict[str, object]] = []
    current_session: dict[str, object] | None = None

    for block_index in range(0, len(payload), FLUKE_LOGGING_BYTES_PER_BLOCK):
        block = payload[block_index : block_index + FLUKE_LOGGING_BYTES_PER_BLOCK]
        tag = block[0]
        if tag == FLUKE_LOGGING_HEADER_TAG:
            current_session = _decode_logging_header_block(block, len(sessions) + 1)
            sessions.append(current_session)
            continue
        if tag not in {FLUKE_LOGGING_DETAIL_TAG, FLUKE_LOGGING_DUAL_READING_DETAIL_TAG}:
            entry = {
                "session_index": None if current_session is None else current_session["session_index"],
                "block_index": (block_index // FLUKE_LOGGING_BYTES_PER_BLOCK) + 1,
                "tag": tag,
                "tag_hex": f"0x{tag:02x}",
                "raw_hex": block.hex(" "),
                "parse_error": "unknown_block_tag",
            }
            if current_session is None:
                sessions.append({"orphan_block": entry})
            else:
                current_session.setdefault("unknown_blocks", []).append(entry)
            continue
        if current_session is None:
            raise ValueError("Encountered logging detail block before any header block.")
        current_session.setdefault("details", []).append(_decode_logging_detail_block(block, current_session))

    return sessions


def _decode_logging_header_block(block: bytes, session_index: int) -> dict[str, object]:
    primary_unit_code = block[1]
    secondary_unit_code = block[2]
    interval_seconds = int.from_bytes(block[4:6], byteorder="little", signed=False)
    start_tool_seconds = int.from_bytes(block[6:10], byteorder="little", signed=False)
    end_tool_seconds = int.from_bytes(block[10:14], byteorder="little", signed=False)
    detail_bytes = int.from_bytes(block[14:18], byteorder="little", signed=False)
    return {
        "session_index": session_index,
        "tag_hex": f"0x{block[0]:02x}",
        "raw_hex": block.hex(" "),
        "primary_unit_code": primary_unit_code,
        "primary_unit_label": FLUKE_LOGGING_UNIT_LABELS.get(primary_unit_code, "unknown"),
        "secondary_unit_code": secondary_unit_code,
        "secondary_unit_label": FLUKE_LOGGING_UNIT_LABELS.get(secondary_unit_code, "unknown"),
        "reading_selector": block[3],
        "interval_seconds": interval_seconds,
        "start_tool_seconds": start_tool_seconds,
        "start_time_utc": _format_unix_seconds(start_tool_seconds),
        "end_tool_seconds": end_tool_seconds,
        "end_time_utc": _format_unix_seconds(end_tool_seconds),
        "detail_bytes": detail_bytes,
        "detail_count": detail_bytes // FLUKE_LOGGING_BYTES_PER_BLOCK,
        "details": [],
    }


def _decode_logging_detail_block(block: bytes, session: dict[str, object]) -> dict[str, object]:
    tag = block[0]
    use_primary = bool(session["reading_selector"] == 0 or tag == FLUKE_LOGGING_DUAL_READING_DETAIL_TAG)
    unit_code = int(session["primary_unit_code"] if use_primary else session["secondary_unit_code"])
    reading_index = 0 if use_primary else 1
    base_timestamp = int(session["start_tool_seconds"])
    capture_offset_seconds = int.from_bytes(block[10:14], byteorder="little", signed=False)
    min_offset_seconds = int.from_bytes(block[14:18], byteorder="little", signed=False)
    return {
        "tag_hex": f"0x{tag:02x}",
        "raw_hex": block.hex(" "),
        "reading_index": reading_index,
        "unit_code": unit_code,
        "unit_label": FLUKE_LOGGING_UNIT_LABELS.get(unit_code, "unknown"),
        "average": _decode_logging_value(block[1], block[4:6]),
        "maximum": _decode_logging_value(block[2], block[6:8]),
        "minimum": _decode_logging_value(block[3], block[8:10]),
        "capture_offset_seconds": capture_offset_seconds,
        "capture_time_utc": _format_unix_seconds(base_timestamp + capture_offset_seconds),
        "min_offset_seconds": min_offset_seconds,
        "min_time_utc": _format_unix_seconds(base_timestamp + min_offset_seconds),
    }


def _decode_logging_value(meta_byte: int, value_bytes: bytes) -> dict[str, object]:
    decimal_places = meta_byte & 0b11
    magnitude_code = (meta_byte >> 2) & 0b111
    state_code = (meta_byte >> 5) & 0b111
    raw_value = int.from_bytes(value_bytes, byteorder="little", signed=True)
    exponent = FLUKE_LOGGING_MAGNITUDE_EXPONENTS.get(magnitude_code, 0)
    scaled_value = raw_value * (10 ** (exponent - decimal_places))
    return {
        "meta_byte_hex": f"0x{meta_byte:02x}",
        "decimal_places": decimal_places,
        "magnitude_code": magnitude_code,
        "magnitude_exponent": exponent,
        "state_code": state_code,
        "state_label": FLUKE_LOGGING_READING_STATE_LABELS.get(state_code, "unknown"),
        "raw_value": raw_value,
        "scaled_value": scaled_value,
    }


def _format_unix_seconds(seconds: int) -> str | None:
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


class _LegacyFluke376FCProfile(DeviceProfile):
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


_CLAMP_METER_FAMILY_ID = "fluke_clamp_meter"
_ADVANCED_CLAMP_FAMILY_ID = "fluke_advanced_clamp"
_HIGH_VOLTAGE_CLAMP_FAMILY_ID = "fluke_high_voltage_clamp"

_CLAMP_METER_LIVE_CAPABILITIES: tuple[str, ...] = (
    "live_reading",
    "stream_notifications",
    "live_scalar",
    "ac_voltage",
    "dc_voltage",
    "dc_current",
    "ac_current",
    "inrush_current",
    "frequency",
    "capacitance",
    "resistance",
)

_CLAMP_METER_LOGGING_CAPABILITIES: tuple[str, ...] = (
    "device_logging_config",
    "device_memory_download",
    "device_memory_clear",
    "session_import",
)

_CLAMP_METER_VARIANTS: dict[str, dict[str, object]] = {
    "374fc": {"model_name": "Fluke 374 FC", "aliases": ("374fc", "fluke374fc"), "logging": False},
    "375fc": {"model_name": "Fluke 375 FC", "aliases": ("375fc", "fluke375fc"), "logging": True},
    "376fc": {"model_name": "Fluke 376 FC", "aliases": ("376fc", "fluke376fc"), "logging": True},
    "368fc": {"model_name": "Fluke 368 FC", "aliases": ("368fc", "fluke368fc"), "logging": True},
    "369fc": {"model_name": "Fluke 369 FC", "aliases": ("369fc", "fluke369fc"), "logging": True},
    "902fc": {"model_name": "Fluke 902 FC", "aliases": ("902fc", "fluke902fc"), "logging": False},
}

_ADVANCED_CLAMP_VARIANTS: dict[str, dict[str, object]] = {
    "377fc": {"model_name": "Fluke 377 FC", "aliases": ("377fc", "fluke377fc"), "family_id": _ADVANCED_CLAMP_FAMILY_ID},
    "378fc": {"model_name": "Fluke 378 FC", "aliases": ("378fc", "fluke378fc"), "family_id": _ADVANCED_CLAMP_FAMILY_ID},
    "393fc": {"model_name": "Fluke 393 FC", "aliases": ("393fc", "fluke393fc"), "family_id": _HIGH_VOLTAGE_CLAMP_FAMILY_ID},
}

_ADVANCED_CLAMP_CAPABILITIES: tuple[str, ...] = (
    "live_reading",
    "stream_notifications",
    "live_scalar",
    "live_primary_secondary",
    "fieldsense_view",
    "phase_rotation_view",
    "phase_to_phase_view",
    "relative_mode_view",
    "continuity_state_view",
    "self_check_view",
)

_ADVANCED_CLAMP_READING_WIDTHS = (21, 4, 3, 3, 1, 8, 8, 7, 3, 5, 1)
_ADVANCED_CLAMP_MODE_ATTR_WIDTHS = (4, 4, 4, 3, 1)
_ADVANCED_CLAMP_VALID_STATE_CODES = {0, 4, 5, 9, 12}
_ADVANCED_CLAMP_BLANK_STATE_CODES = {1, 3, 13}
_ADVANCED_CLAMP_MAGNITUDE_PREFIXES: dict[int, str] = {
    0: "",
    1: "G",
    2: "M",
    3: "k",
    4: "m",
    5: "u",
    6: "n",
    7: "p",
    9: "P",
    10: "T",
}
_ADVANCED_CLAMP_UNIT_LABELS: dict[int, str] = {
    0: "",
    1: "V",
    2: "V",
    3: "A",
    4: "A",
    5: "Hz",
    11: "ohm",
    12: "S",
    13: "%",
    15: "F",
    21: "PSI",
    28: "Bar",
    29: "Pa",
    31: "dBV",
    33: "V",
    34: "A",
    36: "VAC/Hz",
    44: "TOhm",
    45: "V",
    47: "V",
}


def _variant_capabilities(*, logging_enabled: bool) -> tuple[str, ...]:
    if not logging_enabled:
        return _CLAMP_METER_LIVE_CAPABILITIES
    return _CLAMP_METER_LIVE_CAPABILITIES + _CLAMP_METER_LOGGING_CAPABILITIES


def _normalized_device_tokens(advertisement_name: str | None, metadata: dict[str, object]) -> set[str]:
    values = {
        advertisement_name or "",
        str(metadata.get("advertisement_name") or ""),
        str(metadata.get("device_name") or ""),
        str(metadata.get("model_name") or ""),
        str(metadata.get("model_number") or ""),
    }
    return {value.lower().replace(" ", "").replace("-", "") for value in values if value}


def _service_uuid_present(metadata: dict[str, object], service_uuid: str) -> bool:
    service_uuids = metadata.get("service_uuids")
    if not isinstance(service_uuids, list):
        return False
    return service_uuid.lower() in {str(item).lower() for item in service_uuids}


class _ClampMeterRuntime(DeviceFamilyRuntime):
    def __init__(self, profile: "FlukeClampMeterFamilyProfile", match: DeviceMatch) -> None:
        self._profile = profile
        self._match = match

    def family_id(self) -> str:
        return self._match.family_id

    def variant_id(self) -> str:
        return self._match.variant_id

    def capabilities(self) -> tuple[str, ...]:
        return self._match.capabilities

    def notification_subscriptions(self) -> list[str]:
        return [FLUKE_MEAS_UUID, FLUKE_STATUS_UUID]

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        return self._profile._parse_notification_for_variant(
            self._match.variant_id,
            characteristic_uuid=characteristic_uuid,
            payload=payload,
            device_id=device_id,
            observed_at=observed_at,
        )

    def services(self) -> DeviceServiceSet:
        return self._profile._services_for_variant(self._match.variant_id)

    def reset_device(self, device_id: str) -> None:
        self._profile.reset_device(device_id)


class FlukeClampMeterFamilyProfile(_LegacyFluke376FCProfile):
    profile_id = "fluke_clamp_meter_family"
    model_name = "Fluke Clamp Meter Family"

    def __init__(self, fixed_variant_id: str | None = None) -> None:
        super().__init__()
        self._fixed_variant_id = fixed_variant_id

    def family_id(self) -> str:
        return _CLAMP_METER_FAMILY_ID

    def variant_id(self) -> str:
        return self._fixed_variant_id or "clamp_meter_family"

    def display_name(self) -> str:
        if self._fixed_variant_id is not None:
            return str(_CLAMP_METER_VARIANTS[self._fixed_variant_id]["model_name"])
        return self.model_name

    def matches(self, advertisement_name: str | None, metadata: dict[str, object]) -> bool:
        return self._detect_variant(advertisement_name, metadata) is not None

    def match_score(self, advertisement_name: str | None, metadata: dict[str, object]) -> float:
        variant_id = self._detect_variant(advertisement_name, metadata)
        if variant_id is not None:
            return 220.0
        if _service_uuid_present(metadata, FLUKE_ADV_SERVICE_UUID):
            return 25.0
        return 0.0

    def create_match(self, advertisement_name: str | None, metadata: dict[str, object]) -> DeviceMatch | None:
        score = self.match_score(advertisement_name, metadata)
        if score <= 0:
            return None
        variant_id = self._detect_variant(advertisement_name, metadata) or self._fixed_variant_id or "376fc"
        config = _CLAMP_METER_VARIANTS.get(variant_id, _CLAMP_METER_VARIANTS["376fc"])
        return DeviceMatch(
            profile_id=self.profile_id,
            family_id=_CLAMP_METER_FAMILY_ID,
            variant_id=variant_id,
            score=score,
            display_name=str(config["model_name"]),
            model_hint=str(config["model_name"]),
            capabilities=_variant_capabilities(logging_enabled=bool(config["logging"])),
            advertisement_name=advertisement_name,
            metadata=dict(metadata),
        )

    def capabilities(self) -> list[str]:
        variant_id = self._fixed_variant_id or "376fc"
        config = _CLAMP_METER_VARIANTS.get(variant_id, _CLAMP_METER_VARIANTS["376fc"])
        return list(_variant_capabilities(logging_enabled=bool(config["logging"])))

    def create_runtime(self, match: DeviceMatch) -> DeviceFamilyRuntime:
        return _ClampMeterRuntime(self, match)

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        return self._parse_notification_for_variant(
            self._fixed_variant_id or "376fc",
            characteristic_uuid=characteristic_uuid,
            payload=payload,
            device_id=device_id,
            observed_at=observed_at,
        )

    def _parse_notification_for_variant(
        self,
        variant_id: str,
        *,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        readings = super().parse_notification(characteristic_uuid, payload, device_id, observed_at=observed_at)
        if not readings:
            return readings
        sample_group_id = f"{device_id}:{(observed_at or datetime.now(timezone.utc)).isoformat()}"
        enriched: list[Reading] = []
        for reading in readings:
            metadata = dict(reading.metadata)
            metadata.setdefault("family_id", _CLAMP_METER_FAMILY_ID)
            metadata.setdefault("variant_id", variant_id)
            metadata.setdefault("sample_group_id", sample_group_id)
            metadata.setdefault("channel_role", "primary")
            enriched.append(replace(reading, metadata=metadata))
        return enriched

    def _services_for_variant(self, variant_id: str) -> DeviceServiceSet:
        config = _CLAMP_METER_VARIANTS.get(variant_id, _CLAMP_METER_VARIANTS["376fc"])
        logging_enabled = bool(config["logging"])
        logging_descriptor = None
        settings_descriptor = None
        memory_descriptor = None
        if logging_enabled:
            logging_descriptor = {
                "service_uuid": FLUKE_LOGGING_SERVICE_UUID,
                "status_uuid": FLUKE_LOGGING_STATUS_UUID,
                "control_point_uuid": FLUKE_LOGGING_CONTROL_POINT_UUID,
            }
            settings_descriptor = {
                "config_uuid": FLUKE_LOGGING_CONFIG_UUID,
            }
            memory_descriptor = {
                "buffer_uuid": FLUKE_LOGGING_BUFFER_UUID,
                "capacity_uuid": FLUKE_LOGGING_CAPACITY_UUID,
            }
        return DeviceServiceSet(
            live_reading_service={"measurement_uuid": FLUKE_MEAS_UUID, "status_uuid": FLUKE_STATUS_UUID},
            logging_service=logging_descriptor,
            device_memory_service=memory_descriptor,
            settings_service=settings_descriptor,
            family_view_adapter={"family_id": _CLAMP_METER_FAMILY_ID, "variant_id": variant_id},
        )

    def _detect_variant(self, advertisement_name: str | None, metadata: dict[str, object]) -> str | None:
        tokens = _normalized_device_tokens(advertisement_name, metadata)
        candidates = (_CLAMP_METER_VARIANTS.keys() if self._fixed_variant_id is None else (self._fixed_variant_id,))
        for variant_id in candidates:
            config = _CLAMP_METER_VARIANTS[variant_id]
            aliases = tuple(str(item) for item in config["aliases"])
            for alias in aliases:
                if alias in tokens:
                    return variant_id
        return None


@dataclass(frozen=True, slots=True)
class _AdvancedClampBleReading:
    state_code: int
    decimal_places: int
    magnitude_code: int
    sign: bool
    unit_code: int
    function_code: int
    capture_flag: bool
    raw_counts: int

    @property
    def unit_text(self) -> str:
        prefix = _ADVANCED_CLAMP_MAGNITUDE_PREFIXES.get(self.magnitude_code, "")
        unit = _ADVANCED_CLAMP_UNIT_LABELS.get(self.unit_code, "")
        return f"{prefix}{unit}".strip()

    @property
    def is_valid(self) -> bool:
        return self.state_code in _ADVANCED_CLAMP_VALID_STATE_CODES

    @property
    def is_blank(self) -> bool:
        return self.state_code in _ADVANCED_CLAMP_BLANK_STATE_CODES

    @property
    def reading_status(self) -> ReadingStatus:
        if self.state_code == 0:
            return ReadingStatus.OK
        if self.state_code in {4, 5}:
            return ReadingStatus.OVER_RANGE
        if self.state_code in {9, 12}:
            return ReadingStatus.OK
        if self.state_code == 6:
            return ReadingStatus.NO_SIGNAL
        return ReadingStatus.INVALID

    @property
    def numeric_value(self) -> float | None:
        if not self.is_valid:
            return None
        value = self.raw_counts / (10 ** self.decimal_places)
        if self.sign:
            value = -value
        return float(value)


def _unpack_lsb_fields(payload: bytes, widths: tuple[int, ...]) -> list[int]:
    value = int.from_bytes(payload, byteorder="little", signed=False)
    values: list[int] = []
    offset = 0
    for width in widths:
        values.append((value >> offset) & ((1 << width) - 1))
        offset += width
    return values


def _decode_advanced_clamp_reading(payload: bytes) -> _AdvancedClampBleReading:
    fields = _unpack_lsb_fields(payload, _ADVANCED_CLAMP_READING_WIDTHS)
    return _AdvancedClampBleReading(
        raw_counts=fields[0],
        state_code=fields[1],
        decimal_places=fields[2],
        magnitude_code=fields[3],
        sign=bool(fields[4]),
        unit_code=fields[5],
        function_code=fields[6],
        capture_flag=bool(fields[10]),
    )


def _advanced_clamp_mode_labels(mode_attrs: tuple[int, int, int, int, int]) -> list[str]:
    attr1, attr2, attr3, attr4, attr5 = mode_attrs
    labels: list[str] = []
    if attr1 == 8:
        labels.append("Relative")
    elif attr1 in {1, 2, 3, 4, 5, 6, 7}:
        labels.append("PQ")
    if attr2 == 2:
        labels.append("Clockwise")
    elif attr2 == 3:
        labels.append("Counter Clockwise")
    elif attr2 == 4:
        labels.append("Min")
    elif attr2 == 5:
        labels.append("Max")
    elif attr2 == 6:
        labels.append("Avg")
    elif attr2 == 8:
        labels.append("Auto Hold")
    if attr3 == 7:
        labels.append("Clamp")
    elif attr3 == 8:
        labels.append("iFlex")
    elif attr3 in {1, 2, 3, 4, 5, 6}:
        labels.append(f"Phase {attr3}")
    if attr4 == 1:
        labels.append("Phase To Phase")
    elif attr4 == 2:
        labels.append("Hold")
    elif attr4 == 3:
        labels.append("Inrush")
    if attr5 == 1:
        labels.append("Ground Not Connected")
    return labels


def _advanced_clamp_measurement_type(function_code: int, unit_code: int) -> MeasurementType:
    if function_code in {1, 2, 4, 5, 7}:
        return MeasurementType.VOLTAGE_AC
    if function_code in {3}:
        return MeasurementType.VOLTAGE_AC_DC
    if function_code in {8, 9, 24, 25, 47}:
        return MeasurementType.LOW_PASS_VFD
    if function_code in {10, 11, 12}:
        return MeasurementType.VOLTAGE_DC
    if function_code in {13, 14, 16, 17}:
        return MeasurementType.CURRENT_AC
    if function_code in {15, 18}:
        return MeasurementType.CURRENT_AC_DC
    if function_code in {19, 20, 21, 31, 32, 33}:
        return MeasurementType.CURRENT_DC
    if function_code in {22, 23, 24, 25, 26, 27, 28, 29, 30} or unit_code == 5:
        return MeasurementType.FREQUENCY
    if function_code in {34, 35, 36, 37, 38}:
        return MeasurementType.TEMPERATURE
    if function_code == 39:
        return MeasurementType.CONTINUITY
    if function_code in {40, 42}:
        return MeasurementType.RESISTANCE
    if function_code == 41:
        return MeasurementType.CONDUCTANCE
    if function_code == 44:
        return MeasurementType.CURRENT_INRUSH
    if function_code == 45:
        return MeasurementType.CAPACITANCE
    if function_code == 68:
        return MeasurementType.PHASE_ROTATION
    if function_code == 86:
        return MeasurementType.PRESSURE
    if function_code in {87, 88}:
        return MeasurementType.FIELDSENSE
    if function_code == 95:
        return MeasurementType.UNKNOWN_FAMILY_MODE
    if unit_code == 12:
        return MeasurementType.CONDUCTANCE
    return MeasurementType.UNKNOWN


def _advanced_clamp_mode_token(function_code: int) -> str:
    if function_code in {1, 2, 4, 5, 7, 13, 14, 16, 17}:
        return "ac"
    if function_code in {10, 11, 12, 19, 20, 21}:
        return "dc"
    if function_code in {3, 15, 18}:
        return "acdc"
    if function_code == 44:
        return "inrush"
    if function_code in {8, 9, 24, 25, 47}:
        return "vfd"
    if function_code in {87, 88}:
        return "fieldsense"
    if function_code == 68:
        return "phase_rotation"
    return ""


def _advanced_clamp_unit_family(measurement_type: MeasurementType) -> str:
    if measurement_type in {MeasurementType.VOLTAGE_AC, MeasurementType.VOLTAGE_DC, MeasurementType.VOLTAGE_AC_DC}:
        return "voltage"
    if measurement_type in {MeasurementType.CURRENT_AC, MeasurementType.CURRENT_DC, MeasurementType.CURRENT_AC_DC, MeasurementType.CURRENT_INRUSH}:
        return "current"
    if measurement_type == MeasurementType.RESISTANCE:
        return "resistance"
    if measurement_type == MeasurementType.CAPACITANCE:
        return "capacitance"
    if measurement_type == MeasurementType.FREQUENCY:
        return "frequency"
    if measurement_type == MeasurementType.DUTY_CYCLE:
        return "duty_cycle"
    if measurement_type == MeasurementType.TEMPERATURE:
        return "temperature"
    if measurement_type == MeasurementType.CONDUCTANCE:
        return "conductance"
    if measurement_type == MeasurementType.PRESSURE:
        return "pressure"
    return "unknown"


def _format_advanced_clamp_display(reading: _AdvancedClampBleReading) -> str:
    if reading.reading_status == ReadingStatus.OK and reading.numeric_value is not None:
        prefix = ""
        if reading.state_code == 9:
            prefix = "> "
        elif reading.state_code == 12:
            prefix = "< "
        return f"{prefix}{reading.numeric_value:.6g} {reading.unit_text}".strip()
    if reading.state_code in {4, 5}:
        return f"{'-' if reading.sign else ''}OL {reading.unit_text}".strip()
    if reading.state_code == 6:
        return "Open TC"
    if reading.is_blank:
        return ""
    return "invalid"


class _AdvancedClampRuntime(DeviceFamilyRuntime):
    def __init__(self, profile: "FlukeAdvancedClampFamilyProfile", match: DeviceMatch) -> None:
        self._profile = profile
        self._match = match

    def family_id(self) -> str:
        return self._match.family_id

    def variant_id(self) -> str:
        return self._match.variant_id

    def capabilities(self) -> tuple[str, ...]:
        return self._match.capabilities

    def notification_subscriptions(self) -> list[str]:
        return [FLUKE_MEAS_UUID, FLUKE_STATUS_UUID]

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        return self._profile._parse_variant_notification(
            self._match,
            characteristic_uuid=characteristic_uuid,
            payload=payload,
            device_id=device_id,
            observed_at=observed_at,
        )

    def services(self) -> DeviceServiceSet:
        return DeviceServiceSet(
            live_reading_service={"measurement_uuid": FLUKE_MEAS_UUID, "status_uuid": FLUKE_STATUS_UUID},
            family_view_adapter={"family_id": self._match.family_id, "variant_id": self._match.variant_id},
        )


class FlukeAdvancedClampFamilyProfile(DeviceProfile):
    profile_id = "fluke_advanced_clamp_family"
    model_name = "Fluke Advanced Clamp Family"

    def matches(self, advertisement_name: str | None, metadata: dict[str, object]) -> bool:
        return self._detect_variant(advertisement_name, metadata) is not None

    def match_score(self, advertisement_name: str | None, metadata: dict[str, object]) -> float:
        if self._detect_variant(advertisement_name, metadata) is not None:
            return 230.0
        if _service_uuid_present(metadata, FLUKE_ADV_SERVICE_UUID):
            return 10.0
        return 0.0

    def create_match(self, advertisement_name: str | None, metadata: dict[str, object]) -> DeviceMatch | None:
        score = self.match_score(advertisement_name, metadata)
        if score <= 0:
            return None
        variant_id = self._detect_variant(advertisement_name, metadata) or "377fc"
        config = _ADVANCED_CLAMP_VARIANTS[variant_id]
        return DeviceMatch(
            profile_id=self.profile_id,
            family_id=str(config["family_id"]),
            variant_id=variant_id,
            score=score,
            display_name=str(config["model_name"]),
            model_hint=str(config["model_name"]),
            capabilities=_ADVANCED_CLAMP_CAPABILITIES,
            advertisement_name=advertisement_name,
            metadata=dict(metadata),
        )

    def family_id(self) -> str:
        return _ADVANCED_CLAMP_FAMILY_ID

    def capabilities(self) -> list[str]:
        return list(_ADVANCED_CLAMP_CAPABILITIES)

    def notification_characteristics(self) -> list[str]:
        return [FLUKE_MEAS_UUID, FLUKE_STATUS_UUID]

    def create_runtime(self, match: DeviceMatch) -> DeviceFamilyRuntime:
        return _AdvancedClampRuntime(self, match)

    def parse_notification(
        self,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        match = DeviceMatch(
            profile_id=self.profile_id,
            family_id=_ADVANCED_CLAMP_FAMILY_ID,
            variant_id="377fc",
            score=1.0,
            display_name="Fluke 377 FC",
            model_hint="Fluke 377 FC",
            capabilities=_ADVANCED_CLAMP_CAPABILITIES,
        )
        return self._parse_variant_notification(
            match,
            characteristic_uuid=characteristic_uuid,
            payload=payload,
            device_id=device_id,
            observed_at=observed_at,
        )

    def _detect_variant(self, advertisement_name: str | None, metadata: dict[str, object]) -> str | None:
        tokens = _normalized_device_tokens(advertisement_name, metadata)
        for variant_id, config in _ADVANCED_CLAMP_VARIANTS.items():
            for alias in tuple(str(item) for item in config["aliases"]):
                if alias in tokens:
                    return variant_id
        return None

    def _parse_variant_notification(
        self,
        match: DeviceMatch,
        *,
        characteristic_uuid: str,
        payload: bytes,
        device_id: str,
        observed_at: datetime | None = None,
    ) -> list[Reading]:
        del characteristic_uuid
        if len(payload) < 18:
            return []
        observed_at = observed_at or datetime.now(timezone.utc)
        primary = _decode_advanced_clamp_reading(payload[0:8])
        secondary = _decode_advanced_clamp_reading(payload[8:16])
        mode_attrs = tuple(_unpack_lsb_fields(payload[16:18], _ADVANCED_CLAMP_MODE_ATTR_WIDTHS))
        badges = _advanced_clamp_mode_labels(mode_attrs)
        sample_group_id = f"{device_id}:{observed_at.isoformat()}"
        readings: list[Reading] = []
        for channel_role, ble_reading in (("primary", primary), ("secondary", secondary)):
            if ble_reading.is_blank:
                continue
            measurement_type = _advanced_clamp_measurement_type(ble_reading.function_code, ble_reading.unit_code)
            metadata = {
                "family_id": match.family_id,
                "variant_id": match.variant_id,
                "sample_group_id": sample_group_id,
                "channel_role": channel_role,
                "mode_attr_1": mode_attrs[0],
                "mode_attr_2": mode_attrs[1],
                "mode_attr_3": mode_attrs[2],
                "mode_attr_4": mode_attrs[3],
                "mode_attr_5": mode_attrs[4],
                "source_function_code": ble_reading.function_code,
                "source_unit_code": ble_reading.unit_code,
                "source_state_code": ble_reading.state_code,
                "fieldsense": str(primary.function_code in {87, 88} and secondary.function_code in {87, 88}).lower(),
                "phase_to_phase": str(mode_attrs[3] == 1 or ble_reading.function_code == 88).lower(),
                "relative_mode": str(mode_attrs[0] == 8).lower(),
                "continuity_test": str(primary.function_code == 39).lower(),
                "self_check": str(primary.function_code == 95).lower(),
                "family_mode_badges": badges,
                "unit_family": _advanced_clamp_unit_family(measurement_type),
            }
            if not ble_reading.is_valid and channel_role == "secondary":
                continue
            readings.append(
                Reading(
                    timestamp_utc=observed_at,
                    value=ble_reading.numeric_value,
                    unit=ble_reading.unit_text,
                    measurement_type=measurement_type,
                    status=ble_reading.reading_status,
                    display_text=_format_advanced_clamp_display(ble_reading),
                    source_device_id=device_id,
                    mode=_advanced_clamp_mode_token(ble_reading.function_code),
                    raw_payload=payload,
                    metadata=metadata,
                )
            )
        return readings


class Fluke376FCProfile(FlukeClampMeterFamilyProfile):
    profile_id = "fluke_376fc"
    model_name = "Fluke 376 FC"

    def __init__(self) -> None:
        super().__init__(fixed_variant_id="376fc")

    def matches(self, advertisement_name: str | None, metadata: dict[str, object]) -> bool:
        candidates = [
            advertisement_name or "",
            str(metadata.get("advertisement_name") or ""),
        ]
        for candidate in candidates:
            token = candidate.lower().replace(" ", "")
            if "376fc" in token or ("fluke" in token and "376" in token):
                return True
        return _service_uuid_present(metadata, FLUKE_ADV_SERVICE_UUID)

    def match_score(self, advertisement_name: str | None, metadata: dict[str, object]) -> float:
        if self.matches(advertisement_name, metadata):
            return 260.0
        return 0.0
