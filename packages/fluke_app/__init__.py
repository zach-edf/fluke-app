"""Application-layer orchestration services."""

from typing import TYPE_CHECKING, Any

from fluke_app.bus import EventBus
from fluke_app.debug_bundle import export_debug_bundle
from fluke_app.export_service import ExportService
from fluke_app.session_recorder import SessionRecorder, new_session
from fluke_app.workflow_catalog import WorkflowCatalog, default_workflow_directory, load_workflow_catalog
from fluke_app.workflow_runner import WorkflowRunner

if TYPE_CHECKING:
    from fluke_app.device_manager import DeviceManager
    from fluke_app.reading_stream import ReadingStreamService

__all__ = [
    "DeviceManager",
    "EventBus",
    "ExportService",
    "ReadingStreamService",
    "SessionRecorder",
    "export_debug_bundle",
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
    if name == "ReadingStreamService":
        from fluke_app.reading_stream import ReadingStreamService as _ReadingStreamService

        return _ReadingStreamService
    raise AttributeError(name)
