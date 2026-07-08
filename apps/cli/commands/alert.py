"""Stream readings with threshold-based alerts.

Prints each reading and triggers a visual + audible alert (bell)
when the value crosses configured thresholds, the meter reports an
out-of-band status, or the connection drops.

Alarm logic lives in the shared ``AlertEvaluator`` service so the CLI and the
desktop app behave identically.

Activated via: fluke alert --device <id> --high 120 --low 10
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from apps.cli.formatters import format_reading, nonneg_float
from apps.cli.runtime import (
    attach_connection_diagnostics,
    build_device_manager,
    build_speech_service,
    add_speech_arguments,
)
from fluke_app import AlertConfig, AlertEvaluator, AlertKind
from fluke_core.models.reading import Reading


# ANSI color codes
_GREEN = "\033[32m"
_RED = "\033[31m"
_BOLD = "\033[1m"
_RESET = "\033[0m"


def register(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    parser = subparsers.add_parser(
        "alert",
        help="Stream readings and alert when value crosses thresholds",
    )
    parser.add_argument("--device", required=True, help="BLE device identifier from scan output")
    parser.add_argument("--profile", default="fluke_376fc", help="Device profile id to use")
    parser.add_argument("--high", type=float, default=None, help="Alert when reading exceeds this value")
    parser.add_argument("--low", type=float, default=None, help="Alert when reading drops below this value")
    parser.add_argument(
        "--debounce",
        type=nonneg_float,
        default=0.0,
        help="Require the value to stay out of band for N seconds before alerting",
    )
    parser.add_argument("--no-status-alerts", action="store_false", dest="status_alerts", default=True, help="Do not alert on over-range/no-signal status")
    parser.add_argument("--duration", type=nonneg_float, default=0.0, help="Stop after N seconds; 0 runs until interrupted")
    parser.add_argument("--bell", action="store_true", default=True, help="Sound terminal bell on alert (default: on)")
    parser.add_argument("--no-bell", action="store_false", dest="bell", help="Disable terminal bell")
    add_speech_arguments(parser)
    parser.set_defaults(func=handle)


async def handle(args: argparse.Namespace) -> int:
    if args.high is None and args.low is None and not args.status_alerts:
        print("Warning: no thresholds set. Use --high and/or --low to enable alerts.", file=sys.stderr)

    evaluator = AlertEvaluator(
        AlertConfig(
            high=args.high,
            low=args.low,
            debounce_seconds=args.debounce,
            status_alerts=args.status_alerts,
            connection_alerts=True,
        )
    )
    speech = build_speech_service(args)

    manager = build_device_manager()
    attach_connection_diagnostics(manager)
    alert_count = 0
    finished = asyncio.Event()
    terminal_error: str | None = None

    def on_reading(reading: Reading) -> None:
        nonlocal alert_count
        evaluation = evaluator.evaluate(reading)
        line = format_reading(reading)

        if evaluation.active:
            if evaluation.just_triggered:
                alert_count += 1
                if speech is not None:
                    speech.speak_alert(evaluation.message)
            reason = evaluation.message.split(":", 1)[0] if ":" in evaluation.message else evaluation.kind.value.upper()
            prefix = f"{_BOLD}{_RED}ALERT {reason}{_RESET} "
            bell = "\a" if (args.bell and evaluation.just_triggered) else ""
            print(f"{bell}{prefix}{line}")
        else:
            print(f"{_GREEN}✓{_RESET} {line}")
            if speech is not None:
                speech.on_reading(reading)

    manager.subscribe_readings(on_reading)
    manager.subscribe_disconnects(lambda: _handle_disconnect(manager, evaluator, finished, _set_terminal_error))

    def _set_terminal_error(message: str) -> None:
        nonlocal terminal_error
        terminal_error = message

    thresholds = []
    if args.low is not None:
        thresholds.append(f"low={args.low}")
    if args.high is not None:
        thresholds.append(f"high={args.high}")
    if args.debounce:
        thresholds.append(f"debounce={args.debounce}s")
    threshold_text = ", ".join(thresholds) if thresholds else "status only"

    print(f"Connecting to {args.device}...", file=sys.stderr)
    await manager.establish_session(args.device, profile_id=args.profile)
    print(f"Streaming with alerts ({threshold_text}). Press Ctrl+C to stop.", file=sys.stderr)

    try:
        if args.duration > 0:
            await asyncio.wait_for(finished.wait(), timeout=args.duration)
        else:
            await finished.wait()
    except asyncio.TimeoutError:
        pass
    finally:
        await manager.disconnect()
        if alert_count:
            print(f"\n{_RED}{alert_count} alert(s) triggered.{_RESET}", file=sys.stderr)

    if terminal_error:
        print(f"Alert stream ended because recovery failed: {terminal_error}", file=sys.stderr)
        return 1
    return 0


def _handle_disconnect(manager, evaluator: AlertEvaluator, finished: asyncio.Event, set_message) -> None:
    status = manager.latest_connection_diagnostics()
    detail = "" if status is None else (status.last_error_text or status.message)
    evaluator.note_connection_lost(detail)
    set_message(detail)
    finished.set()
