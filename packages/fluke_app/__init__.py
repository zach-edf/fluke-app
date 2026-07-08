"""Application-layer orchestration services."""

from typing import TYPE_CHECKING, Any

from fluke_app.alerts import (
    AlertConfig,
    AlertEvaluation,
    AlertEvaluator,
    AlertKind,
)
from fluke_app.bus import EventBus
from fluke_app.device_logging import (
    build_logging_session_previews,
    clear_logging_data,
    LOGGING_VALUE_SOURCES,
    download_logging_data,
    import_logging_sessions,
    read_logging_config,
    read_logging_status,
    write_logging_config,
)
from fluke_app.asset_trend_service import (
    AssetTrend,
    AssetTrendService,
    TrendPoint,
    TrendSeries,
    export_asset_trend_csv,
)
from fluke_app.export_service import ExportService
from fluke_app.report_service import ReportService
from fluke_app.session_recorder import SessionRecorder, new_session
from fluke_app.workflow_catalog import WorkflowCatalog, default_workflow_directory, load_workflow_catalog
from fluke_app.workflow_runner import WorkflowRunner

if TYPE_CHECKING:
    from fluke_app.device_manager import (
        ConnectionAttemptStatus,
        ConnectionRetryPolicy,
        ConnectionStateChanged,
        DeviceManager,
    )
    from fluke_app.reading_stream import ReadingStreamService
    from fluke_app.reconnect_policy import ReconnectPolicy
    from fluke_app.session_continuity import SessionConnectionMarkers

__all__ = [
    "AlertConfig",
    "AlertEvaluation",
    "AlertEvaluator",
    "AlertKind",
    "AssetTrend",
    "AssetTrendService",
    "DeviceManager",
    "EventBus",
    "ExportService",
    "MqttConfig",
    "MqttPublisher",
    "SpeechConfig",
    "SpeechMode",
    "SpeechService",
    "TrendPoint",
    "TrendSeries",
    "export_asset_trend_csv",
    "reading_to_speech_text",
    "select_backend",
    "LOGGING_VALUE_SOURCES",
    "ReadingStreamService",
    "ReportService",
    "SessionRecorder",
    "build_logging_session_previews",
    "clear_logging_data",
    "ConnectionAttemptStatus",
    "ConnectionRetryPolicy",
    "ConnectionStateChanged",
    "ReconnectPolicy",
    "SessionConnectionMarkers",
    "download_logging_data",
    "export_debug_bundle",
    "import_logging_sessions",
    "read_logging_config",
    "read_logging_status",
    "write_logging_config",
    "WorkflowCatalog",
    "WorkflowRunner",
    "default_workflow_directory",
    "load_workflow_catalog",
    "new_session",
]


def __getattr__(name: str) -> Any:
    if name == "DeviceManager":
        from fluke_app.device_manager import DeviceManager as _DeviceManager

        return _DeviceManager
    if name == "ConnectionRetryPolicy":
        from fluke_app.device_manager import ConnectionRetryPolicy as _ConnectionRetryPolicy

        return _ConnectionRetryPolicy
    if name == "ConnectionAttemptStatus":
        from fluke_app.device_manager import ConnectionAttemptStatus as _ConnectionAttemptStatus

        return _ConnectionAttemptStatus
    if name == "ConnectionStateChanged":
        from fluke_app.device_manager import ConnectionStateChanged as _ConnectionStateChanged

        return _ConnectionStateChanged
    if name == "ReconnectPolicy":
        from fluke_app.reconnect_policy import ReconnectPolicy as _ReconnectPolicy

        return _ReconnectPolicy
    if name == "SessionConnectionMarkers":
        from fluke_app.session_continuity import SessionConnectionMarkers as _SessionConnectionMarkers

        return _SessionConnectionMarkers
    if name == "ReadingStreamService":
        from fluke_app.reading_stream import ReadingStreamService as _ReadingStreamService

        return _ReadingStreamService
    if name == "export_debug_bundle":
        from fluke_app.debug_bundle import export_debug_bundle as _export_debug_bundle

        return _export_debug_bundle
    if name in {"SpeechConfig", "SpeechMode", "SpeechService", "reading_to_speech_text", "select_backend"}:
        import fluke_app.speech_service as _speech

        return getattr(_speech, name)
    if name in {"MqttConfig", "MqttPublisher"}:
        import fluke_app.mqtt_publisher as _mqtt

        return getattr(_mqtt, name)
    raise AttributeError(name)
