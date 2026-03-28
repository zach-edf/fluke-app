from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from fluke_core.models.session import Session


class SessionRepository:
    def __init__(self, con: sqlite3.Connection):
        self._con = con

    def create(self, session: Session) -> Session:
        self._con.execute(
            """
            INSERT INTO sessions (
                session_id, device_id, started_at, ended_at,
                title, notes, tags_json, app_version, profile_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                device_id=excluded.device_id,
                started_at=excluded.started_at,
                ended_at=excluded.ended_at,
                title=excluded.title,
                notes=excluded.notes,
                tags_json=excluded.tags_json,
                app_version=excluded.app_version,
                profile_id=excluded.profile_id
            """,
            (
                session.session_id,
                session.device_id,
                session.started_at.isoformat(),
                session.ended_at.isoformat() if session.ended_at else None,
                session.title,
                session.notes,
                json.dumps(session.tags),
                session.app_version,
                session.profile_id,
            ),
        )
        self._con.commit()
        return session

    def update(self, session: Session) -> Session:
        return self.create(session)

    def get(self, session_id: str) -> Session | None:
        row = self._con.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return _session_from_row(row)

    def list_recent(self, limit: int = 20) -> list[Session]:
        rows = self._con.execute(
            """
            SELECT * FROM sessions
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_session_from_row(row) for row in rows]


def _session_from_row(row: sqlite3.Row) -> Session:
    return Session(
        session_id=row["session_id"],
        device_id=row["device_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
        title=row["title"],
        notes=row["notes"],
        tags=json.loads(row["tags_json"]) if row["tags_json"] else [],
        app_version=row["app_version"],
        profile_id=row["profile_id"],
    )
