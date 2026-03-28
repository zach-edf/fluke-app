from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

from fluke_app.ports import ReadingRepository, SessionRepository
from fluke_core.models.reading import Reading
from fluke_core.models.session import Session


class SessionRecorder:
    def __init__(self, session_repo: SessionRepository, reading_repo: ReadingRepository) -> None:
        self._session_repo = session_repo
        self._reading_repo = reading_repo
        self._active_session: Session | None = None
        self._reading_count = 0

    def start(self, session: Session) -> Session:
        self._active_session = session
        self._reading_count = 0
        self._session_repo.create(session)
        return session

    def stop(self, ended_at: datetime | None = None) -> Session | None:
        if self._active_session is None:
            return None

        ended = ended_at or datetime.now(timezone.utc)
        finished = replace(self._active_session, ended_at=ended)
        self._session_repo.update(finished)
        self._active_session = None
        return finished

    def on_reading(self, reading: Reading) -> None:
        if self._active_session is None:
            return
        self._reading_repo.append(self._active_session.session_id, reading)
        self._reading_count += 1

    def active_session(self) -> Session | None:
        return self._active_session

    def reading_count(self) -> int:
        return self._reading_count


def new_session(
    device_id: str,
    *,
    title: str | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
    app_version: str | None = None,
    profile_id: str | None = None,
    started_at: datetime | None = None,
) -> Session:
    started = started_at or datetime.now(timezone.utc)
    return Session(
        session_id=_session_id(),
        device_id=device_id,
        started_at=started,
        ended_at=None,
        title=title,
        notes=notes,
        tags=list(tags or []),
        app_version=app_version,
        profile_id=profile_id,
    )


def _session_id() -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
