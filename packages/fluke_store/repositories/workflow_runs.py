from __future__ import annotations

from contextlib import nullcontext
import sqlite3
from datetime import datetime

from fluke_core.enums import WorkflowRunResult
from fluke_core.models.workflow import WorkflowRun


class WorkflowRunRepository:
    def __init__(self, con: sqlite3.Connection, lock=None):
        self._con = con
        self._lock = lock or nullcontext()

    def create(self, run: WorkflowRun) -> WorkflowRun:
        with self._lock:
            self._con.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_id, session_id, started_at, ended_at, result, workflow_title
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    workflow_id=excluded.workflow_id,
                    session_id=excluded.session_id,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    result=excluded.result,
                    workflow_title=excluded.workflow_title
                """,
                (
                    run.run_id,
                    run.workflow_id,
                    run.session_id,
                    run.started_at.isoformat(),
                    run.ended_at.isoformat() if run.ended_at else None,
                    run.result.value,
                    run.workflow_title,
                ),
            )
            self._con.commit()
        return run

    def update(self, run: WorkflowRun) -> WorkflowRun:
        return self.create(run)

    def get(self, run_id: str) -> WorkflowRun | None:
        with self._lock:
            row = self._con.execute("SELECT * FROM workflow_runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return _run_from_row(row)

    def list_recent(self, limit: int = 20) -> list[WorkflowRun]:
        with self._lock:
            rows = self._con.execute(
                """
                SELECT * FROM workflow_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_run_from_row(row) for row in rows]

    def list_for_session(self, session_id: str) -> list[WorkflowRun]:
        with self._lock:
            rows = self._con.execute(
                """
                SELECT * FROM workflow_runs
                WHERE session_id = ?
                ORDER BY started_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_run_from_row(row) for row in rows]


def _run_from_row(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(
        run_id=row["run_id"],
        workflow_id=row["workflow_id"],
        session_id=row["session_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
        result=WorkflowRunResult(row["result"]),
        workflow_title=row["workflow_title"],
    )
