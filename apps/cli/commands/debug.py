from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fluke_app.device_logging import download_logging_data, read_logging_config, write_logging_config
from apps.cli.formatters import nonneg_float
from apps.cli.runtime import build_workflows, default_database_path, load_extensions
from fluke_app import export_debug_bundle
from fluke_plugins import build_profile_registry


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser("debug", help="Export diagnostics for bug reports and contributor triage")
    debug_subparsers = parser.add_subparsers(dest="debug_command", required=True)

    bundle_parser = debug_subparsers.add_parser("bundle", help="Export a debug bundle zip")
    bundle_parser.add_argument("--output", required=True, help="Zip path to create")
    bundle_parser.add_argument("--database", default=None, help="SQLite database to summarize (default: platform data dir)")
    bundle_parser.set_defaults(func=handle_bundle)

    probe_parser = debug_subparsers.add_parser(
        "probe",
        help="Inspect BLE services and optionally read or capture characteristic traffic",
    )
    probe_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    probe_parser.add_argument("--read", action="store_true", help="Attempt a read on readable characteristics")
    probe_parser.add_argument(
        "--notify-seconds",
        type=nonneg_float,
        default=0.0,
        help="Subscribe to notify/indicate characteristics for N seconds",
    )
    probe_parser.add_argument("--output", default=None, help="Optional JSON file to write the probe report to")
    probe_parser.set_defaults(func=handle_probe)

    transact_parser = debug_subparsers.add_parser(
        "transact",
        help="Read, write, and capture notifications for a specific BLE characteristic",
    )
    transact_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    transact_parser.add_argument("--char", required=True, help="Characteristic UUID to target")
    transact_parser.add_argument("--read-before", action="store_true", help="Read the characteristic before writing")
    transact_parser.add_argument("--write-hex", default=None, help="Hex payload to write, for example '01 00 ff'")
    transact_parser.add_argument(
        "--write-mode",
        choices=("auto", "response", "no-response"),
        default="auto",
        help="BLE write mode to use when writing: auto, response, or no-response",
    )
    transact_parser.add_argument("--read-after", action="store_true", help="Read the characteristic after writing")
    transact_parser.add_argument(
        "--notify-seconds",
        type=nonneg_float,
        default=0.0,
        help="Capture notify/indicate traffic on the target characteristic for N seconds",
    )
    transact_parser.add_argument(
        "--settle-seconds",
        type=nonneg_float,
        default=0.25,
        help="Wait time after write before any read-after or notify timeout completes",
    )
    transact_parser.add_argument("--output", default=None, help="Optional JSON file to write the transaction report to")
    transact_parser.set_defaults(func=handle_transact)

    logging_parser = debug_subparsers.add_parser(
        "logging-config",
        help="Read and decode the Fluke 376 FC logging configuration payload",
    )
    logging_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    logging_parser.add_argument("--output", default=None, help="Optional JSON file to write the decoded config to")
    logging_parser.set_defaults(func=handle_logging_config)

    logging_set_parser = debug_subparsers.add_parser(
        "logging-config-set",
        help="Write an experimental Fluke 376 FC logging configuration payload",
    )
    logging_set_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    logging_set_parser.add_argument(
        "--interval-seconds",
        type=int,
        required=True,
        help="Logging interval in seconds",
    )
    logging_set_parser.add_argument(
        "--duration-seconds",
        type=int,
        required=True,
        help="Finite logging duration in seconds",
    )
    logging_set_parser.add_argument("--read-before", action="store_true", help="Read and decode the current payload first")
    logging_set_parser.add_argument("--read-after", action="store_true", help="Read and decode the payload after writing")
    logging_set_parser.add_argument("--output", default=None, help="Optional JSON file to write the report to")
    logging_set_parser.set_defaults(func=handle_logging_config_set)

    logging_download_parser = debug_subparsers.add_parser(
        "logging-download",
        help="Run the validated Fluke 376 FC logging download flow using 2908/2917",
    )
    logging_download_parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    logging_download_parser.add_argument(
        "--data-output",
        default=None,
        help="Optional file path to write the raw downloaded logging bytes",
    )
    logging_download_parser.add_argument(
        "--max-blocks-per-request",
        type=int,
        default=500,
        help="Maximum number of 18-byte blocks to request per 2908 download command",
    )
    logging_download_parser.add_argument(
        "--command-timeout-seconds",
        type=nonneg_float,
        default=5.0,
        help="Maximum time to wait for each lock/download segment step",
    )
    logging_download_parser.add_argument("--output", default=None, help="Optional JSON file to write the report to")
    logging_download_parser.set_defaults(func=handle_logging_download)


async def handle_bundle(args: argparse.Namespace) -> int:
    plugin_bundle = load_extensions()
    workflow_catalog = build_workflows()
    profile_registry = build_profile_registry()
    output = export_debug_bundle(
        args.output,
        profile_registry=profile_registry,
        workflow_catalog=workflow_catalog,
        plugin_bundle=plugin_bundle,
        database_path=args.database or default_database_path(),
    )
    print(output)
    return 0


async def handle_probe(args: argparse.Namespace) -> int:
    from apps.cli.runtime import require_bleak_adapter

    adapter = require_bleak_adapter()()
    await adapter.connect(args.device)
    try:
        report = await _probe_device(
            adapter=adapter,
            device_id=args.device,
            read_characteristics=args.read,
            notify_seconds=args.notify_seconds,
        )
    finally:
        await adapter.disconnect(args.device)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_probe_report(report, output_path=Path(args.output) if args.output else None)
    return 0


async def handle_transact(args: argparse.Namespace) -> int:
    from apps.cli.runtime import require_bleak_adapter

    adapter = require_bleak_adapter()()
    await adapter.connect(args.device)
    try:
        report = await _transact_characteristic(
            adapter=adapter,
            device_id=args.device,
            characteristic_uuid=args.char,
            read_before=args.read_before,
            write_hex=args.write_hex,
            write_mode=args.write_mode,
            read_after=args.read_after,
            notify_seconds=args.notify_seconds,
            settle_seconds=args.settle_seconds,
        )
    finally:
        await adapter.disconnect(args.device)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_transaction_report(report, output_path=Path(args.output) if args.output else None)
    return 0


async def handle_logging_config(args: argparse.Namespace) -> int:
    from apps.cli.runtime import require_bleak_adapter

    adapter = require_bleak_adapter()()
    await adapter.connect(args.device)
    try:
        report = await read_logging_config(adapter, args.device)
    finally:
        await adapter.disconnect(args.device)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_logging_config(report, output_path=Path(args.output) if args.output else None)
    return 0


async def handle_logging_config_set(args: argparse.Namespace) -> int:
    from apps.cli.runtime import require_bleak_adapter

    adapter = require_bleak_adapter()()
    await adapter.connect(args.device)
    try:
        report = await _write_logging_config(
            adapter=adapter,
            device_id=args.device,
            interval_seconds=args.interval_seconds,
            duration_seconds=args.duration_seconds,
            read_before=args.read_before,
            read_after=args.read_after,
        )
    finally:
        await adapter.disconnect(args.device)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_logging_config_write(report, output_path=Path(args.output) if args.output else None)
    return 0


async def handle_logging_download(args: argparse.Namespace) -> int:
    from apps.cli.runtime import require_bleak_adapter

    adapter = require_bleak_adapter()()
    await adapter.connect(args.device)
    try:
        report = await _download_logging_data(
            adapter=adapter,
            device_id=args.device,
            data_output=Path(args.data_output) if args.data_output else None,
            max_blocks_per_request=args.max_blocks_per_request,
            command_timeout_seconds=args.command_timeout_seconds,
        )
    finally:
        await adapter.disconnect(args.device)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        _print_logging_download(report, output_path=Path(args.output) if args.output else None)
    return 0


async def _probe_device(
    adapter: Any,
    device_id: str,
    read_characteristics: bool,
    notify_seconds: float,
) -> dict[str, Any]:
    services = await adapter.services(device_id)
    report: dict[str, Any] = {
        "device_id": device_id,
        "read_attempted": read_characteristics,
        "notify_seconds": notify_seconds,
        "services": [],
    }

    for service in services:
        service_payload: dict[str, Any] = {
            "uuid": service.uuid,
            "description": service.description,
            "characteristics": [],
        }
        for characteristic in service.characteristics:
            characteristic_payload: dict[str, Any] = {
                "uuid": characteristic.uuid,
                "properties": list(characteristic.properties),
            }
            if read_characteristics and _supports_property(characteristic.properties, "read"):
                try:
                    payload = await adapter.read(device_id, characteristic.uuid)
                    characteristic_payload["read_hex"] = payload.hex(" ")
                    characteristic_payload["read_len"] = len(payload)
                except Exception as exc:
                    characteristic_payload["read_error"] = f"{type(exc).__name__}: {exc}"
            service_payload["characteristics"].append(characteristic_payload)
        report["services"].append(service_payload)

    if notify_seconds > 0:
        await _capture_notifications(adapter, device_id, report, notify_seconds)

    return report


async def _write_logging_config(
    adapter: Any,
    device_id: str,
    interval_seconds: int,
    duration_seconds: int,
    read_before: bool,
    read_after: bool,
) -> dict[str, Any]:
    return await write_logging_config(
        adapter,
        device_id,
        interval_seconds=interval_seconds,
        duration_seconds=duration_seconds,
        read_before=read_before,
        read_after=read_after,
    )


async def _download_logging_data(
    adapter: Any,
    device_id: str,
    data_output: Path | None,
    max_blocks_per_request: int,
    command_timeout_seconds: float,
) -> dict[str, Any]:
    return await download_logging_data(
        adapter=adapter,
        device_id=device_id,
        data_output=data_output,
        max_blocks_per_request=max_blocks_per_request,
        command_timeout_seconds=command_timeout_seconds,
    )


async def _transact_characteristic(
    adapter: Any,
    device_id: str,
    characteristic_uuid: str,
    read_before: bool,
    write_hex: str | None,
    write_mode: str,
    read_after: bool,
    notify_seconds: float,
    settle_seconds: float,
) -> dict[str, Any]:
    import asyncio

    services = await adapter.services(device_id)
    characteristic = _find_characteristic(services, characteristic_uuid)
    normalized_uuid = str(characteristic["uuid"])
    report: dict[str, Any] = {
        "device_id": device_id,
        "characteristic_uuid": normalized_uuid,
        "service_uuid": characteristic["service_uuid"],
        "service_description": characteristic["service_description"],
        "properties": list(characteristic["properties"]),
        "read_before": read_before,
        "read_after": read_after,
        "write_hex": None if write_hex is None else _normalize_hex_string(write_hex),
        "write_mode": write_mode,
        "notify_seconds": notify_seconds,
        "settle_seconds": settle_seconds,
        "notifications": [],
    }

    notifications: list[dict[str, Any]] = []
    subscribed = False
    if notify_seconds > 0 and _supports_property(characteristic["properties"], "notify", "indicate"):
        async def _callback(data: bytes) -> None:
            notifications.append({"len": len(data), "hex": data.hex(" ")})

        try:
            await adapter.subscribe(device_id, normalized_uuid, _callback)
            subscribed = True
        except Exception as exc:
            report["subscribe_error"] = f"{type(exc).__name__}: {exc}"

    try:
        if read_before:
            report["read_before_result"] = await _safe_read(adapter, device_id, normalized_uuid)

        if write_hex is not None:
            payload = _parse_hex_payload(write_hex)
            report["write_len"] = len(payload)
            try:
                response_mode: bool | None
                if write_mode == "auto":
                    response_mode = None
                elif write_mode == "response":
                    response_mode = True
                else:
                    response_mode = False
                await adapter.write(device_id, normalized_uuid, payload, response=response_mode)
                report["write_ok"] = True
            except Exception as exc:
                report["write_ok"] = False
                report["write_error"] = f"{type(exc).__name__}: {exc}"

        if settle_seconds > 0:
            await asyncio.sleep(settle_seconds)
        if notify_seconds > 0:
            remaining = max(notify_seconds - settle_seconds, 0.0)
            if remaining > 0:
                await asyncio.sleep(remaining)

        if read_after:
            report["read_after_result"] = await _safe_read(adapter, device_id, normalized_uuid)
    finally:
        if subscribed:
            try:
                await adapter.unsubscribe(device_id, normalized_uuid)
            except Exception:
                pass

    report["notifications"] = notifications
    report["notification_count"] = len(notifications)
    return report


async def _capture_notifications(
    adapter: Any,
    device_id: str,
    report: dict[str, Any],
    notify_seconds: float,
) -> None:
    import asyncio

    active: list[str] = []
    captures: dict[str, list[dict[str, Any]]] = {}

    for service in report["services"]:
        for characteristic in service["characteristics"]:
            if not _supports_property(characteristic["properties"], "notify", "indicate"):
                continue

            characteristic_uuid = str(characteristic["uuid"])
            captures[characteristic_uuid] = []

            async def _callback(data: bytes, *, target_uuid: str = characteristic_uuid) -> None:
                captures[target_uuid].append(
                    {
                        "len": len(data),
                        "hex": data.hex(" "),
                    }
                )

            try:
                await adapter.subscribe(device_id, characteristic_uuid, _callback)
                active.append(characteristic_uuid)
            except Exception as exc:
                characteristic["subscribe_error"] = f"{type(exc).__name__}: {exc}"

    if active:
        await asyncio.sleep(notify_seconds)

    for characteristic_uuid in active:
        try:
            await adapter.unsubscribe(device_id, characteristic_uuid)
        except Exception:
            pass

    for service in report["services"]:
        for characteristic in service["characteristics"]:
            characteristic_uuid = str(characteristic["uuid"])
            if characteristic_uuid in captures:
                characteristic["notifications"] = captures[characteristic_uuid]
                characteristic["notification_count"] = len(captures[characteristic_uuid])


def _supports_property(properties: list[str] | tuple[str, ...], *candidates: str) -> bool:
    normalized = {prop.lower() for prop in properties}
    return any(candidate.lower() in normalized for candidate in candidates)


def _find_characteristic(services: list[Any], characteristic_uuid: str) -> dict[str, Any]:
    target = characteristic_uuid.lower()
    for service in services:
        for characteristic in service.characteristics:
            candidate_uuid = str(characteristic.uuid)
            if candidate_uuid.lower() == target:
                return {
                    "uuid": candidate_uuid,
                    "properties": characteristic.properties,
                    "service_uuid": service.uuid,
                    "service_description": service.description,
                }
    raise RuntimeError(f"Characteristic {characteristic_uuid!r} not found on connected device.")


async def _safe_read(adapter: Any, device_id: str, characteristic_uuid: str) -> dict[str, Any]:
    try:
        payload = await adapter.read(device_id, characteristic_uuid)
        return {
            "ok": True,
            "len": len(payload),
            "hex": payload.hex(" "),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def _parse_hex_payload(raw: str) -> bytes:
    cleaned = "".join(str(raw).split())
    if not cleaned:
        return b""
    try:
        return bytes.fromhex(cleaned)
    except ValueError as exc:
        raise RuntimeError(f"Invalid --write-hex payload: {raw!r}") from exc


def _normalize_hex_string(raw: str) -> str:
    return _parse_hex_payload(raw).hex(" ")


def _print_probe_report(report: dict[str, Any], output_path: Path | None) -> None:
    print(f"Device: {report['device_id']}")
    print(f"Services: {len(report['services'])}")
    print(f"Read attempted: {'yes' if report['read_attempted'] else 'no'}")
    if report["notify_seconds"] > 0:
        print(f"Notification capture: {report['notify_seconds']:.2f}s")
    if output_path is not None:
        print(f"Saved JSON: {output_path}")
    print()

    for service in report["services"]:
        label = service["description"] or "(no description)"
        print(f"Service {service['uuid']} | {label}")
        for characteristic in service["characteristics"]:
            properties = ", ".join(characteristic["properties"]) or "-"
            print(f"  Char {characteristic['uuid']} | props={properties}")
            if "read_hex" in characteristic:
                print(f"    read[{characteristic['read_len']}]={characteristic['read_hex']}")
            if "read_error" in characteristic:
                print(f"    read_error={characteristic['read_error']}")
            if "subscribe_error" in characteristic:
                print(f"    subscribe_error={characteristic['subscribe_error']}")
            if "notification_count" in characteristic:
                print(f"    notifications={characteristic['notification_count']}")
                for entry in characteristic["notifications"][:5]:
                    print(f"      [{entry['len']}] {entry['hex']}")
                extra = characteristic["notification_count"] - len(characteristic["notifications"][:5])
                if extra > 0:
                    print(f"      ... {extra} more")
        print()


def _print_transaction_report(report: dict[str, Any], output_path: Path | None) -> None:
    print(f"Device: {report['device_id']}")
    print(f"Service: {report['service_uuid']} | {report['service_description'] or '(no description)'}")
    print(f"Characteristic: {report['characteristic_uuid']}")
    print(f"Properties: {', '.join(report['properties']) or '-'}")
    if report["write_hex"] is not None:
        print(f"Write mode: {report['write_mode']}")
        print(f"Write[{report.get('write_len', 0)}]: {report['write_hex']}")
        print(f"Write OK: {'yes' if report.get('write_ok') else 'no'}")
    if output_path is not None:
        print(f"Saved JSON: {output_path}")
    print()

    if "read_before_result" in report:
        _print_read_result("Read before", report["read_before_result"])
    if "write_error" in report:
        print(f"Write error: {report['write_error']}")
    if "read_after_result" in report:
        _print_read_result("Read after", report["read_after_result"])
    if "subscribe_error" in report:
        print(f"Subscribe error: {report['subscribe_error']}")
    print(f"Notifications: {report['notification_count']}")
    for entry in report["notifications"][:10]:
        print(f"  [{entry['len']}] {entry['hex']}")
    extra = report["notification_count"] - len(report["notifications"][:10])
    if extra > 0:
        print(f"  ... {extra} more")


def _print_read_result(label: str, result: dict[str, Any]) -> None:
    if result.get("ok"):
        print(f"{label}[{result['len']}]: {result['hex']}")
    else:
        print(f"{label} error: {result['error']}")


def _print_logging_config(report: dict[str, Any], output_path: Path | None) -> None:
    print(f"Device: {report['device_id']}")
    print(f"Characteristic: {report['characteristic_uuid']}")
    print(f"Interval: {report['interval_seconds']} second(s)")
    print(f"Duration: {report['duration_seconds']} second(s)")
    print(f"Payload: {report['payload_hex']}")
    if output_path is not None:
        print(f"Saved JSON: {output_path}")


def _print_logging_config_write(report: dict[str, Any], output_path: Path | None) -> None:
    print(f"Device: {report['device_id']}")
    print(f"Characteristic: {report['characteristic_uuid']}")
    print(f"Requested interval: {report['requested_interval_seconds']} second(s)")
    print(f"Requested duration: {report['requested_duration_seconds']} second(s)")
    print(f"Write payload: {report['write_payload_hex']}")
    print(f"Write OK: {'yes' if report['write_ok'] else 'no'}")
    if "write_error" in report:
        print(f"Write error: {report['write_error']}")
    if "read_before" in report:
        print("Read before:")
        print(f"  interval={report['read_before']['interval_seconds']}")
        print(f"  duration={report['read_before']['duration_seconds']}")
        print(f"  payload={report['read_before']['payload_hex']}")
    if "read_after" in report:
        print("Read after:")
        print(f"  interval={report['read_after']['interval_seconds']}")
        print(f"  duration={report['read_after']['duration_seconds']}")
        print(f"  payload={report['read_after']['payload_hex']}")
    if output_path is not None:
        print(f"Saved JSON: {output_path}")


def _print_logging_download(report: dict[str, Any], output_path: Path | None) -> None:
    print(f"Device: {report['device_id']}")
    print(f"Service: {report['service_uuid']}")
    print(
        "Status before: "
        f"{report['status_before']['state_label']} "
        f"(bytes_logged={report['status_before']['bytes_logged']}, "
        f"blocks_logged={report['status_before']['blocks_logged']})"
    )
    if "capacity_bytes" in report:
        print(f"Capacity: {report['capacity_bytes']} byte(s)")
    print(f"Did lock for download: {'yes' if report.get('did_lock_for_download') else 'no'}")
    if "status_locked" in report:
        print(
            "Status locked: "
            f"{report['status_locked']['state_label']} "
            f"(bytes_logged={report['status_locked']['bytes_logged']}, "
            f"blocks_logged={report['status_locked']['blocks_logged']})"
        )
    print(f"Expected blocks: {report.get('expected_total_blocks', 0)}")
    print(f"Expected bytes: {report.get('expected_total_bytes', 0)}")
    print(f"Downloaded bytes: {report.get('downloaded_bytes', 0)}")
    print(f"Downloaded blocks: {report.get('downloaded_blocks', 0)}")
    print(f"Control notifications: {len(report.get('control_notifications', []))}")
    print(f"Buffer notifications: {len(report.get('buffer_notifications', []))}")
    decoded_sessions = report.get("decoded_sessions", [])
    if decoded_sessions:
        print(f"Decoded sessions: {len(decoded_sessions)}")
        first = decoded_sessions[0]
        if isinstance(first, dict) and "session_index" in first:
            print(
                "First session: "
                f"unit={first.get('primary_unit_label')} "
                f"interval={first.get('interval_seconds')}s "
                f"start={first.get('start_time_utc')} "
                f"end={first.get('end_time_utc')} "
                f"details={len(first.get('details', []))}"
            )
    if "decode_error" in report:
        print(f"Decode error: {report['decode_error']}")
    if "data_output" in report:
        print(f"Saved raw data: {report['data_output']}")
    if "download_warning" in report:
        print(f"Warning: {report['download_warning']}")
    if "unlock_error" in report:
        print(f"Unlock error: {report['unlock_error']}")
    if "subscribe_errors" in report:
        print("Subscribe errors:")
        for characteristic_uuid, error in report["subscribe_errors"].items():
            print(f"  {characteristic_uuid}: {error}")
    if output_path is not None:
        print(f"Saved JSON: {output_path}")
