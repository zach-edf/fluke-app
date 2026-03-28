from __future__ import annotations

from pathlib import Path
from typing import Protocol

from fluke_core.models.reading import Reading
from fluke_core.models.session import Session


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
