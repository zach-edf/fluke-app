from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from fluke_app.ports import DeviceRepository, ReadingRepository, SessionRepository
from fluke_core.enums import ReadingStatus
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_protocol.profiles.fluke_376fc import (
    decode_logging_download_payload,
    describe_logging_unit_code,
    FLUKE_LOGGING_BUFFER_UUID,
    FLUKE_LOGGING_BYTES_PER_BLOCK,
    FLUKE_LOGGING_CAPACITY_UUID,
    FLUKE_LOGGING_CONFIG_UUID,
    FLUKE_LOGGING_CONTROL_POINT_CODES,
    FLUKE_LOGGING_CONTROL_POINT_UUID,
    FLUKE_LOGGING_SERVICE_UUID,
    FLUKE_LOGGING_STATE_LABELS,
    FLUKE_LOGGING_STATUS_UUID,
    Fluke376FCLoggingConfig,
    Fluke376FCLoggingStatus,
    logging_state_code_to_reading_status,
)

LoggingValueSource = Literal["average", "maximum", "minimum"]
LOGGING_VALUE_SOURCES: tuple[LoggingValueSource, ...] = ("average", "maximum", "minimum")


async def read_logging_config(adapter: Any, device_id: str) -> dict[str, Any]:
    payload = await adapter.read(device_id, FLUKE_LOGGING_CONFIG_UUID)
    config = Fluke376FCLoggingConfig.from_payload(payload)
    return {
        "device_id": device_id,
        "characteristic_uuid": FLUKE_LOGGING_CONFIG_UUID,
        **config.as_dict(),
    }


async def read_logging_status(adapter: Any, device_id: str) -> dict[str, Any]:
    status_payload = await adapter.read(device_id, FLUKE_LOGGING_STATUS_UUID)
    status = Fluke376FCLoggingStatus.from_payload(status_payload)
    report: dict[str, Any] = {
        "device_id": device_id,
        "status_uuid": FLUKE_LOGGING_STATUS_UUID,
        "capacity_uuid": FLUKE_LOGGING_CAPACITY_UUID,
        **status.as_dict(),
    }
    try:
        capacity_payload = await adapter.read(device_id, FLUKE_LOGGING_CAPACITY_UUID)
        capacity_bytes = _decode_logging_capacity(capacity_payload)
        report["capacity_bytes"] = capacity_bytes
        report["capacity_payload_hex"] = capacity_payload.hex(" ")
        report["percent_full"] = 0.0 if capacity_bytes <= 0 else round((status.bytes_logged / capacity_bytes) * 100.0, 2)
    except Exception as exc:
        report["capacity_error"] = f"{type(exc).__name__}: {exc}"
    return report


async def write_logging_config(
    adapter: Any,
    device_id: str,
    *,
    interval_seconds: int,
    duration_seconds: int,
    read_before: bool = False,
    read_after: bool = True,
) -> dict[str, Any]:
    report: dict[str, Any] = {
        "device_id": device_id,
        "characteristic_uuid": FLUKE_LOGGING_CONFIG_UUID,
        "requested_interval_seconds": interval_seconds,
        "requested_duration_seconds": duration_seconds,
        "write_ok": False,
    }

    if read_before:
        before_payload = await adapter.read(device_id, FLUKE_LOGGING_CONFIG_UUID)
        report["read_before"] = Fluke376FCLoggingConfig.from_payload(before_payload).as_dict()

    config = Fluke376FCLoggingConfig(
        interval_seconds=interval_seconds,
        duration_seconds=duration_seconds,
    )
    payload = config.to_payload()
    report["write_payload_hex"] = payload.hex(" ")
    try:
        await adapter.write(device_id, FLUKE_LOGGING_CONFIG_UUID, payload)
        report["write_ok"] = True
    except Exception as exc:
        report["write_error"] = f"{type(exc).__name__}: {exc}"
        return report

    if read_after:
        after_payload = await adapter.read(device_id, FLUKE_LOGGING_CONFIG_UUID)
        report["read_after"] = Fluke376FCLoggingConfig.from_payload(after_payload).as_dict()
    return report


async def download_logging_data(
    adapter: Any,
    device_id: str,
    *,
    data_output: Path | None = None,
    max_blocks_per_request: int = 500,
    command_timeout_seconds: float = 5.0,
) -> dict[str, Any]:
    import asyncio

    if max_blocks_per_request <= 0:
        raise RuntimeError("--max-blocks-per-request must be positive.")

    status_payload = await adapter.read(device_id, FLUKE_LOGGING_STATUS_UUID)
    status_before = Fluke376FCLoggingStatus.from_payload(status_payload)
    report: dict[str, Any] = {
        "device_id": device_id,
        "service_uuid": FLUKE_LOGGING_SERVICE_UUID,
        "status_uuid": FLUKE_LOGGING_STATUS_UUID,
        "control_point_uuid": FLUKE_LOGGING_CONTROL_POINT_UUID,
        "download_buffer_uuid": FLUKE_LOGGING_BUFFER_UUID,
        "capacity_uuid": FLUKE_LOGGING_CAPACITY_UUID,
        "status_before": status_before.as_dict(),
        "max_blocks_per_request": max_blocks_per_request,
        "command_timeout_seconds": command_timeout_seconds,
    }
    try:
        capacity_payload = await adapter.read(device_id, FLUKE_LOGGING_CAPACITY_UUID)
        report["capacity_bytes"] = _decode_logging_capacity(capacity_payload)
        report["capacity_payload_hex"] = capacity_payload.hex(" ")
    except Exception as exc:
        report["capacity_error"] = f"{type(exc).__name__}: {exc}"

    if status_before.blocks_logged <= 0:
        report["downloaded_bytes"] = 0
        report["downloaded_blocks"] = 0
        report["did_lock_for_download"] = False
        report["control_notifications"] = []
        report["status_notifications"] = []
        report["buffer_notifications"] = []
        report["download_segments"] = []
        report["decoded_sessions"] = []
        return report

    live_state: dict[str, Any] = {
        "status": status_before,
        "downloaded": bytearray(),
        "control_notifications": [],
        "status_notifications": [],
        "buffer_notifications": [],
    }

    async def _status_callback(data: bytes) -> None:
        entry: dict[str, Any] = {"len": len(data), "hex": data.hex(" ")}
        try:
            decoded = Fluke376FCLoggingStatus.from_payload(data)
            live_state["status"] = decoded
            entry.update(decoded.as_dict())
        except ValueError as exc:
            entry["parse_error"] = str(exc)
        live_state["status_notifications"].append(entry)

    async def _control_callback(data: bytes) -> None:
        code = data[0] if data else None
        entry: dict[str, Any] = {"len": len(data), "hex": data.hex(" ")}
        if code is not None:
            entry["response_code"] = code
            entry["response_label"] = _logging_control_response_label(code)
        live_state["control_notifications"].append(entry)

    async def _buffer_callback(data: bytes) -> None:
        live_state["downloaded"].extend(data)
        live_state["buffer_notifications"].append(
            {
                "len": len(data),
                "hex_preview": data[: min(16, len(data))].hex(" "),
            }
        )

    subscribed: list[tuple[str, Any]] = []
    did_lock_for_download = False
    try:
        for characteristic_uuid, callback in (
            (FLUKE_LOGGING_STATUS_UUID, _status_callback),
            (FLUKE_LOGGING_CONTROL_POINT_UUID, _control_callback),
            (FLUKE_LOGGING_BUFFER_UUID, _buffer_callback),
        ):
            try:
                await adapter.subscribe(device_id, characteristic_uuid, callback)
                subscribed.append((characteristic_uuid, callback))
            except Exception as exc:
                report.setdefault("subscribe_errors", {})[characteristic_uuid] = f"{type(exc).__name__}: {exc}"

        if status_before.state_code != 4:
            did_lock_for_download = True
            await adapter.write(
                device_id,
                FLUKE_LOGGING_CONTROL_POINT_UUID,
                bytes([FLUKE_LOGGING_CONTROL_POINT_CODES["lock_for_download"]]),
            )
            await _wait_for_logging_state(
                adapter=adapter,
                device_id=device_id,
                live_state=live_state,
                expected_state_code=4,
                timeout_seconds=command_timeout_seconds,
            )
        report["did_lock_for_download"] = did_lock_for_download
        report["status_locked"] = live_state["status"].as_dict()

        total_blocks = live_state["status"].blocks_logged
        total_bytes_expected = total_blocks * FLUKE_LOGGING_BYTES_PER_BLOCK
        report["expected_total_blocks"] = total_blocks
        report["expected_total_bytes"] = total_bytes_expected

        current_start_block = 1
        remaining_blocks = total_blocks
        segments: list[dict[str, Any]] = []
        while remaining_blocks > 0:
            blocks_this_request = min(max_blocks_per_request, remaining_blocks)
            expected_segment_bytes = blocks_this_request * FLUKE_LOGGING_BYTES_PER_BLOCK
            control_start_index = len(live_state["control_notifications"])
            buffer_start_len = len(live_state["downloaded"])
            payload = _build_logging_download_request(
                start_block=current_start_block,
                block_count=blocks_this_request,
            )
            await adapter.write(device_id, FLUKE_LOGGING_CONTROL_POINT_UUID, payload)
            await _wait_for_download_segment(
                live_state=live_state,
                control_start_index=control_start_index,
                buffer_start_len=buffer_start_len,
                expected_segment_bytes=expected_segment_bytes,
                timeout_seconds=command_timeout_seconds,
            )
            segments.append(
                {
                    "start_block": current_start_block,
                    "block_count": blocks_this_request,
                    "expected_bytes": expected_segment_bytes,
                    "received_bytes": len(live_state["downloaded"]) - buffer_start_len,
                    "request_hex": payload.hex(" "),
                }
            )
            current_start_block += blocks_this_request
            remaining_blocks -= blocks_this_request
        report["download_segments"] = segments
    finally:
        try:
            await adapter.write(
                device_id,
                FLUKE_LOGGING_CONTROL_POINT_UUID,
                bytes([FLUKE_LOGGING_CONTROL_POINT_CODES["unlock"]]),
            )
            try:
                status_after_unlock = await adapter.read(device_id, FLUKE_LOGGING_STATUS_UUID)
                live_state["status"] = Fluke376FCLoggingStatus.from_payload(status_after_unlock)
            except Exception as exc:
                report["status_after_read_error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            report["unlock_error"] = f"{type(exc).__name__}: {exc}"
        for characteristic_uuid, _ in subscribed:
            try:
                await adapter.unsubscribe(device_id, characteristic_uuid)
            except Exception:
                pass

    downloaded = bytes(live_state["downloaded"])
    report["downloaded_bytes"] = len(downloaded)
    report["downloaded_blocks"] = len(downloaded) // FLUKE_LOGGING_BYTES_PER_BLOCK
    report["status_notifications"] = live_state["status_notifications"]
    report["control_notifications"] = live_state["control_notifications"]
    report["buffer_notifications"] = live_state["buffer_notifications"]
    report["status_after"] = live_state["status"].as_dict()
    if len(downloaded) != report["expected_total_bytes"]:
        report["download_warning"] = (
            f"Expected {report['expected_total_bytes']} byte(s), received {len(downloaded)} byte(s)."
        )

    if data_output is not None:
        data_output.parent.mkdir(parents=True, exist_ok=True)
        data_output.write_bytes(downloaded)
        report["data_output"] = str(data_output)
    try:
        report["decoded_sessions"] = decode_logging_download_payload(downloaded)
    except Exception as exc:
        report["decode_error"] = f"{type(exc).__name__}: {exc}"
    return report


async def clear_logging_data(
    adapter: Any,
    device_id: str,
    *,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    import asyncio

    before = await read_logging_status(adapter, device_id)
    report: dict[str, Any] = {
        "device_id": device_id,
        "control_point_uuid": FLUKE_LOGGING_CONTROL_POINT_UUID,
        "timeout_seconds": timeout_seconds,
        "status_before": before,
        "erase_command_hex": bytes([FLUKE_LOGGING_CONTROL_POINT_CODES["erase_logged_data"]]).hex(" "),
    }
    await adapter.write(
        device_id,
        FLUKE_LOGGING_CONTROL_POINT_UUID,
        bytes([FLUKE_LOGGING_CONTROL_POINT_CODES["erase_logged_data"]]),
    )

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    last_status = Fluke376FCLoggingStatus.from_payload(
        await adapter.read(device_id, FLUKE_LOGGING_STATUS_UUID)
    )
    status_samples = [last_status.as_dict()]
    while True:
        if last_status.state_code == 0 and last_status.bytes_logged == 0 and last_status.blocks_logged == 0:
            break
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(
                "Timed out waiting for device memory erase to complete. "
                f"Last status was {last_status.state_label} with {last_status.bytes_logged} byte(s) "
                f"across {last_status.blocks_logged} block(s)."
            )
        await asyncio.sleep(0.25)
        last_status = Fluke376FCLoggingStatus.from_payload(
            await adapter.read(device_id, FLUKE_LOGGING_STATUS_UUID)
        )
        status_samples.append(last_status.as_dict())

    after = await read_logging_status(adapter, device_id)
    report["status_samples"] = status_samples
    report["status_after"] = after
    return report


def import_logging_sessions(
    *,
    device_repo: DeviceRepository,
    session_repo: SessionRepository,
    reading_repo: ReadingRepository,
    device_id: str,
    decoded_sessions: list[dict[str, object]],
    profile_id: str = "fluke_376fc",
    value_source: LoggingValueSource = "average",
) -> dict[str, Any]:
    if value_source not in LOGGING_VALUE_SOURCES:
        raise ValueError(f"Unsupported logging value source: {value_source!r}")

    _ensure_device_exists(device_repo, device_id=device_id, profile_id=profile_id)

    imported_sessions: list[dict[str, Any]] = []
    skipped_sessions: list[dict[str, Any]] = []
    for decoded_session in decoded_sessions:
        if not isinstance(decoded_session, dict) or "session_index" not in decoded_session:
            continue
        session_id = _device_memory_session_id(device_id, decoded_session)
        existing = session_repo.get(session_id)
        if existing is not None:
            skipped_sessions.append(
                {
                    "session_id": session_id,
                    "session_index": decoded_session.get("session_index"),
                    "reason": "already_imported",
                }
            )
            continue

        session = _build_imported_session(
            device_id=device_id,
            session_id=session_id,
            decoded_session=decoded_session,
            profile_id=profile_id,
            value_source=value_source,
        )
        readings = _build_imported_readings(
            device_id=device_id,
            decoded_session=decoded_session,
            value_source=value_source,
        )
        session_repo.create(session)
        for reading in readings:
            reading_repo.append(session.session_id, reading)
        imported_sessions.append(
            {
                "session_id": session.session_id,
                "session_index": decoded_session.get("session_index"),
                "title": session.title,
                "started_at": session.started_at.isoformat(),
                "ended_at": None if session.ended_at is None else session.ended_at.isoformat(),
                "reading_count": len(readings),
            }
        )

    return {
        "device_id": device_id,
        "profile_id": profile_id,
        "value_source": value_source,
        "decoded_session_count": sum(
            1 for decoded_session in decoded_sessions if isinstance(decoded_session, dict) and "session_index" in decoded_session
        ),
        "imported_count": len(imported_sessions),
        "skipped_count": len(skipped_sessions),
        "imported_sessions": imported_sessions,
        "skipped_sessions": skipped_sessions,
    }


def build_logging_session_previews(
    *,
    session_repo: SessionRepository,
    device_id: str,
    decoded_sessions: list[dict[str, object]],
) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for decoded_session in decoded_sessions:
        if not isinstance(decoded_session, dict) or "session_index" not in decoded_session:
            continue
        session_id = _device_memory_session_id(device_id, decoded_session)
        existing = session_repo.get(session_id)
        started_at = _parse_iso8601(decoded_session.get("start_time_utc"))
        ended_at = _parse_iso8601(decoded_session.get("end_time_utc"))
        previews.append(
            {
                "preview_id": session_id,
                "session_id": session_id,
                "session_index": decoded_session.get("session_index"),
                "title": (
                    f"{decoded_session.get('primary_unit_label') or 'Unknown'} "
                    f"{started_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
                    if started_at is not None
                    else str(decoded_session.get("primary_unit_label") or "Unknown")
                ).strip(),
                "measurement_text": str(decoded_session.get("primary_unit_label") or "Unknown"),
                "started_at_text": "-" if started_at is None else started_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "ended_at_text": "-" if ended_at is None else ended_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                "interval_seconds": int(decoded_session.get("interval_seconds") or 0),
                "detail_count": len(decoded_session.get("details", [])) if isinstance(decoded_session.get("details"), list) else 0,
                "raw_hex": decoded_session.get("raw_hex"),
                "import_status": "Imported" if existing is not None else "Ready",
            }
        )
    return previews


def _ensure_device_exists(device_repo: DeviceRepository, *, device_id: str, profile_id: str) -> None:
    if device_repo.get(device_id) is not None:
        return
    family_id = ""
    variant_id = ""
    model_name = "Fluke 376 FC"
    if profile_id in {"fluke_376fc", "fluke_clamp_meter_family"}:
        family_id = "fluke_clamp_meter"
        variant_id = "376fc"
    device_repo.upsert(
        DeviceInfo(
            device_id=device_id,
            ble_address=device_id,
            model_name=model_name,
            profile_id=profile_id,
            family_id=family_id,
            variant_id=variant_id,
            nickname=None,
            support_level="supported",
        )
    )


def _device_memory_session_id(device_id: str, decoded_session: dict[str, object]) -> str:
    payload = {
        "device_id": device_id,
        "header": decoded_session.get("raw_hex"),
        "detail_hex": [detail.get("raw_hex") for detail in decoded_session.get("details", []) if isinstance(detail, dict)],
    }
    digest = hashlib.sha1(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()[:12]
    started_at = _parse_iso8601(decoded_session.get("start_time_utc")) or datetime.now(timezone.utc)
    return f"mem-{started_at.strftime('%Y%m%dT%H%M%SZ')}-{digest}"


def _build_imported_session(
    *,
    device_id: str,
    session_id: str,
    decoded_session: dict[str, object],
    profile_id: str,
    value_source: LoggingValueSource,
) -> Session:
    started_at = _parse_iso8601(decoded_session.get("start_time_utc")) or datetime.now(timezone.utc)
    ended_at = _parse_iso8601(decoded_session.get("end_time_utc"))
    unit_label = str(decoded_session.get("primary_unit_label") or "Unknown").strip()
    title = f"Device Memory {unit_label} {started_at.strftime('%Y-%m-%d %H:%M:%SZ')}".strip()
    notes = (
        "Imported from device memory. "
        f"Interval={decoded_session.get('interval_seconds', 0)}s, "
        f"detail_count={len(decoded_session.get('details', []))}, "
        f"value_source={value_source}."
    )
    return Session(
        session_id=session_id,
        device_id=device_id,
        started_at=started_at,
        ended_at=ended_at,
        title=title,
        notes=notes,
        tags=["device_memory", "imported"],
        profile_id=profile_id,
    )


def _build_imported_readings(
    *,
    device_id: str,
    decoded_session: dict[str, object],
    value_source: LoggingValueSource,
) -> list[Reading]:
    details = decoded_session.get("details", [])
    if not isinstance(details, list):
        return []

    primary_unit_code = int(decoded_session.get("primary_unit_code") or 0)
    descriptor = describe_logging_unit_code(primary_unit_code)
    readings: list[Reading] = []
    for index, detail in enumerate(details, start=1):
        if not isinstance(detail, dict):
            continue
        selected = detail.get(value_source)
        if not isinstance(selected, dict):
            continue
        timestamp = _detail_timestamp(detail, value_source) or _parse_iso8601(decoded_session.get("start_time_utc"))
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        state_code = int(selected.get("state_code") or 0)
        status = logging_state_code_to_reading_status(state_code)
        value = float(selected.get("scaled_value")) if status == ReadingStatus.OK else None
        metadata = {
            "source": "device_memory",
            "value_source": value_source,
            "session_index": decoded_session.get("session_index"),
            "detail_index": index,
            "detail_tag_hex": detail.get("tag_hex"),
            "unit_code": descriptor.unit_code,
            "unit_label": descriptor.unit_label,
            "unit_family": descriptor.unit_family,
            "function_key": descriptor.function_key,
            "function_label": descriptor.function_label,
            "capture_offset_seconds": detail.get("capture_offset_seconds"),
            "capture_time_utc": detail.get("capture_time_utc"),
            "min_offset_seconds": detail.get("min_offset_seconds"),
            "min_time_utc": detail.get("min_time_utc"),
            "average": detail.get("average"),
            "maximum": detail.get("maximum"),
            "minimum": detail.get("minimum"),
        }
        readings.append(
            Reading(
                timestamp_utc=timestamp,
                value=value,
                unit=descriptor.unit,
                measurement_type=descriptor.measurement_type,
                status=status,
                display_text=_format_imported_display_text(value, descriptor.unit, value_source, selected),
                source_device_id=device_id,
                mode=descriptor.mode,
                raw_payload=_raw_bytes_from_hex(detail.get("raw_hex")),
                metadata=metadata,
            )
        )
    return readings


def _detail_timestamp(detail: dict[str, object], value_source: LoggingValueSource) -> datetime | None:
    if value_source == "minimum":
        return _parse_iso8601(detail.get("min_time_utc")) or _parse_iso8601(detail.get("capture_time_utc"))
    return _parse_iso8601(detail.get("capture_time_utc"))


def _format_imported_display_text(
    value: float | None,
    unit: str,
    value_source: LoggingValueSource,
    selected: dict[str, object],
) -> str:
    if value is None:
        state_label = str(selected.get("state_label") or "invalid").replace("_", " ")
        if state_label == "over limit":
            return f"OL {unit}".strip()
        if state_label == "over limit negative":
            return f"-OL {unit}".strip()
        return state_label
    suffix = "" if value_source == "average" else f" ({value_source})"
    return f"{value:g} {unit}".strip() + suffix


def _parse_iso8601(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    return datetime.fromisoformat(raw)


def _raw_bytes_from_hex(raw_hex: object) -> bytes | None:
    if not isinstance(raw_hex, str) or not raw_hex.strip():
        return None
    return bytes.fromhex("".join(raw_hex.split()))


def _decode_logging_capacity(payload: bytes) -> int:
    if len(payload) < 4:
        raise ValueError(f"Expected at least 4 byte(s) for logging capacity, got {len(payload)}.")
    return int.from_bytes(payload[:4], byteorder="little", signed=False)


def _logging_control_response_label(code: int) -> str:
    labels = {
        0: "idle",
        1: "command_rejected",
        2: "download_active",
        3: "download_complete",
        5: "canceled",
        6: "failed_to_start",
    }
    return labels.get(code, "unknown")


def _build_logging_download_request(start_block: int, block_count: int) -> bytes:
    if start_block <= 0:
        raise ValueError("start_block must be positive.")
    if block_count <= 0:
        raise ValueError("block_count must be positive.")
    return (
        bytes([FLUKE_LOGGING_CONTROL_POINT_CODES["download_request"]])
        + int(start_block).to_bytes(4, byteorder="little", signed=False)
        + int(block_count).to_bytes(4, byteorder="little", signed=False)
    )


async def _wait_for_logging_state(
    *,
    adapter: Any,
    device_id: str,
    live_state: dict[str, Any],
    expected_state_code: int,
    timeout_seconds: float,
) -> Fluke376FCLoggingStatus:
    import asyncio

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        current_status = live_state["status"]
        if current_status.state_code == expected_state_code:
            return current_status
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for logging state {expected_state_code} "
                f"({FLUKE_LOGGING_STATE_LABELS.get(expected_state_code, 'unknown')})."
            )
        await asyncio.sleep(0.25)
        payload = await adapter.read(device_id, FLUKE_LOGGING_STATUS_UUID)
        live_state["status"] = Fluke376FCLoggingStatus.from_payload(payload)


async def _wait_for_download_segment(
    *,
    live_state: dict[str, Any],
    control_start_index: int,
    buffer_start_len: int,
    expected_segment_bytes: int,
    timeout_seconds: float,
) -> None:
    import asyncio

    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        received_segment_bytes = len(live_state["downloaded"]) - buffer_start_len
        if received_segment_bytes >= expected_segment_bytes:
            return
        recent_controls = live_state["control_notifications"][control_start_index:]
        for entry in recent_controls:
            code = entry.get("response_code")
            if code in {1, 5, 6}:
                raise RuntimeError(f"Download control point returned {entry.get('response_label', 'error')}.")
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(
                f"Timed out waiting for {expected_segment_bytes} byte(s) from the logging download buffer; "
                f"received {received_segment_bytes} byte(s)."
            )
        await asyncio.sleep(0.05)
