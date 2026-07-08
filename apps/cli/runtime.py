from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from fluke_app import ConnectionAttemptStatus, DeviceManager, EventBus, ReadingStreamService
from fluke_plugins import build_profile_registry, build_workflow_catalog, load_plugin_bundle
from fluke_store import FlukeStore


def configure_logging(verbose: bool = False) -> None:
    """Set up Python logging based on verbosity."""
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )


def default_database_path() -> str:
    """Return a platform-appropriate default database path.

    macOS:   ~/Library/Application Support/fluke-community/fluke.db
    Linux:   ~/.local/share/fluke-community/fluke.db
    Windows: %LOCALAPPDATA%/fluke-community/fluke.db
    Fallback: data/fluke.db
    """
    app_name = "fluke-community"
    if sys.platform == "darwin":
        db_dir = Path.home() / "Library" / "Application Support" / app_name
    elif sys.platform == "win32":
        db_dir = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / app_name
    elif sys.platform.startswith("linux"):
        db_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / app_name
    else:
        db_dir = Path("data")
    return str(db_dir / "fluke.db")


def require_bleak_adapter() -> type[object]:
    try:
        from fluke_ble.bleak_adapter import BleakAdapter
    except ModuleNotFoundError as exc:
        raise RuntimeError("BLE support requires the `bleak` package. Install `requirements.txt`.") from exc
    return BleakAdapter


def build_device_manager(*, auto_reconnect: bool = True) -> DeviceManager:
    bleak_adapter_cls = require_bleak_adapter()
    return DeviceManager(
        ble_adapter=bleak_adapter_cls(),
        profile_registry=build_profile_registry(),
        event_bus=EventBus(),
        reading_stream=ReadingStreamService(),
        auto_reconnect=auto_reconnect,
    )


def add_reconnect_flag(parser) -> None:
    """Add the shared ``--no-reconnect`` flag to a CLI subcommand parser."""
    parser.add_argument(
        "--no-reconnect",
        dest="no_reconnect",
        action="store_true",
        help="Disable automatic reconnect; a dropped connection ends the command.",
    )


def attach_connection_diagnostics(manager: DeviceManager) -> None:
    last_signature: tuple[object, ...] | None = None

    def _on_status(status: ConnectionAttemptStatus) -> None:
        nonlocal last_signature
        signature = (
            status.phase,
            status.target_device_id,
            status.attempt,
            status.total_attempts,
            status.last_error_text,
            round(status.window_elapsed_s, 1),
        )
        if signature == last_signature:
            return
        last_signature = signature
        phase_label = status.phase.replace("_", " ")
        attempt_label = ""
        if status.total_attempts > 0:
            attempt_label = f" ({status.attempt}/{status.total_attempts})"
        prefix = "recovery" if status.is_recovery else "connect"
        detail = f"[{prefix}:{phase_label}{attempt_label}] {status.message}"
        if status.last_error_text:
            detail = f"{detail} Last error: {status.last_error_text}"
        print(detail, file=sys.stderr)

    manager.subscribe_connection_diagnostics(_on_status)


def open_store(path: str | None = None) -> FlukeStore:
    return FlukeStore(path or default_database_path())


def load_extensions():
    return load_plugin_bundle()


def build_workflows():
    return build_workflow_catalog()


# ---------------------------------------------------------------------------
# Spoken readings (TTS) CLI wiring
# ---------------------------------------------------------------------------

def add_speech_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach --speak / --speak-interval / --speak-mode to a command parser."""
    parser.add_argument("--speak", action="store_true", help="Announce readings aloud using platform TTS")
    parser.add_argument(
        "--speak-mode",
        choices=["interval", "on_stable", "on_change", "on_alert"],
        default="interval",
        help="When to speak readings (default: interval)",
    )
    parser.add_argument("--speak-interval", type=float, default=10.0, help="Seconds between spoken readings in interval mode")
    parser.add_argument("--speak-delta", type=float, default=1.0, help="Minimum change to announce in on_change mode")


def build_speech_service(args: argparse.Namespace):
    """Return a configured SpeechService if --speak was requested, else None."""
    if not getattr(args, "speak", False):
        return None
    from fluke_app import SpeechConfig, SpeechMode, SpeechService

    config = SpeechConfig(
        enabled=True,
        mode=SpeechMode(getattr(args, "speak_mode", "interval")),
        interval_seconds=getattr(args, "speak_interval", 10.0),
        change_delta=getattr(args, "speak_delta", 1.0),
        speak_alerts=True,
    )
    service = SpeechService(config)
    if not service.is_available():
        print(
            "Warning: no platform text-to-speech engine found; --speak has no effect.",
            file=sys.stderr,
        )
    return service


# ---------------------------------------------------------------------------
# MQTT publishing CLI wiring
# ---------------------------------------------------------------------------

def add_mqtt_arguments(parser: argparse.ArgumentParser) -> None:
    """Attach MQTT broker options to a command parser."""
    parser.add_argument("--mqtt-host", default=None, help="MQTT broker host; enables MQTT publishing when set")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883)")
    parser.add_argument("--mqtt-username", default=None, help="MQTT username")
    parser.add_argument("--mqtt-password", default=None, help="MQTT password")
    parser.add_argument("--mqtt-tls", action="store_true", help="Use TLS for the MQTT connection")
    parser.add_argument("--mqtt-topic", default="fluke", help="MQTT base topic (default: fluke)")
    parser.add_argument("--mqtt-qos", type=int, default=0, choices=[0, 1, 2], help="MQTT QoS level (default: 0)")
    parser.add_argument("--mqtt-retain", action="store_true", help="Set the retain flag on published readings")
    parser.add_argument("--mqtt-no-discovery", action="store_true", help="Disable Home Assistant MQTT discovery")


def build_mqtt_publisher(args: argparse.Namespace):
    """Return an MqttPublisher if --mqtt-host was given, else None."""
    host = getattr(args, "mqtt_host", None)
    if not host:
        return None
    from fluke_app import MqttConfig, MqttPublisher

    config = MqttConfig(
        host=host,
        port=getattr(args, "mqtt_port", 1883),
        username=getattr(args, "mqtt_username", None),
        password=getattr(args, "mqtt_password", None),
        use_tls=getattr(args, "mqtt_tls", False),
        base_topic=getattr(args, "mqtt_topic", "fluke"),
        qos=getattr(args, "mqtt_qos", 0),
        retain=getattr(args, "mqtt_retain", False),
        discovery=not getattr(args, "mqtt_no_discovery", False),
    )
    return MqttPublisher(config)
