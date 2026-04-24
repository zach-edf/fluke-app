from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Protocol

from fluke_core.models.device import DeviceInfo
from fluke_core.models.marker import SessionMarker
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session
from fluke_core.models.workflow import WorkflowRun, WorkflowStepResult


class DeviceRepository(Protocol):
    def upsert(self, device: DeviceInfo, last_seen_at: datetime | None = None) -> DeviceInfo:
        ...

    def get(self, device_id: str) -> DeviceInfo | None:
        ...


class SessionRepository(Protocol):
    def create(self, session: Session) -> None:
        ...

    def update(self, session: Session) -> None:
        ...

    def get(self, session_id: str) -> Session | None:
        ...

    def list_recent(self, limit: int = 20) -> list[Session]:
        ...


class ReadingRepository(Protocol):
    def append(self, session_id: str, reading: Reading) -> None:
        ...

    def list_for_session(self, session_id: str) -> list[Reading]:
        ...


class ReadingExporter(Protocol):
    def export(self, session: Session, readings: list[Reading], path: Path) -> Path:
        ...


class MarkerRepository(Protocol):
    def append(self, session_id: str, marker: SessionMarker) -> SessionMarker:
        ...

    def list_for_session(self, session_id: str) -> list[SessionMarker]:
        ...


class WorkflowRunRepository(Protocol):
    def create(self, run: WorkflowRun) -> WorkflowRun:
        ...

    def update(self, run: WorkflowRun) -> WorkflowRun:
        ...

    def get(self, run_id: str) -> WorkflowRun | None:
        ...

    def list_recent(self, limit: int = 20) -> list[WorkflowRun]:
        ...

    def list_for_session(self, session_id: str) -> list[WorkflowRun]:
        ...


class WorkflowStepResultRepository(Protocol):
    def append(self, result: WorkflowStepResult) -> WorkflowStepResult:
        ...

    def list_for_run(self, run_id: str) -> list[WorkflowStepResult]:
        ...
