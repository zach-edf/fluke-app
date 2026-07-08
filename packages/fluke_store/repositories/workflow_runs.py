from __future__ import annotations

from contextlib import nullcontext
import json
import sqlite3
from datetime import datetime

from fluke_core.enums import WorkflowRunResult, WorkflowVerdict
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
                    run_id, workflow_id, session_id, started_at, ended_at, result,
                    workflow_title, verdict, report_meta_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    workflow_id=excluded.workflow_id,
                    session_id=excluded.session_id,
                    started_at=excluded.started_at,
                    ended_at=excluded.ended_at,
                    result=excluded.result,
                    workflow_title=excluded.workflow_title,
                    verdict=excluded.verdict,
                    report_meta_json=excluded.report_meta_json
                """,
                (
                    run.run_id,
                    run.workflow_id,
                    run.session_id,
                    run.started_at.isoformat(),
                    run.ended_at.isoformat() if run.ended_at else None,
                    run.result.value,
                    run.workflow_title,
                    run.verdict.value,
                    json.dumps(run.report_meta or {}, sort_keys=True),
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
    keys = row.keys()
    verdict_raw = row["verdict"] if "verdict" in keys else None
    report_meta_raw = row["report_meta_json"] if "report_meta_json" in keys else None
    report_meta = {}
    if report_meta_raw:
        try:
            report_meta = {str(k): str(v) for k, v in dict(json.loads(report_meta_raw)).items()}
        except (ValueError, TypeError):
            report_meta = {}
    return WorkflowRun(
        run_id=row["run_id"],
        workflow_id=row["workflow_id"],
        session_id=row["session_id"],
        started_at=datetime.fromisoformat(row["started_at"]),
        ended_at=datetime.fromisoformat(row["ended_at"]) if row["ended_at"] else None,
        result=WorkflowRunResult(row["result"]),
        workflow_title=row["workflow_title"],
        verdict=WorkflowVerdict(verdict_raw) if verdict_raw else WorkflowVerdict.NOT_EVALUATED,
        report_meta=report_meta,
    )
