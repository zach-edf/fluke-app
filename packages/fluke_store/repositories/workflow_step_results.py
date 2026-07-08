from __future__ import annotations

from contextlib import nullcontext
import json
import sqlite3
from datetime import datetime

from fluke_core.enums import MeasurementType, ReadingStatus, WorkflowStepResultStatus, WorkflowVerdict
from fluke_core.models.reading import Reading
from fluke_core.models.workflow import WorkflowStepResult


class WorkflowStepResultRepository:
    def __init__(self, con: sqlite3.Connection, lock=None):
        self._con = con
        self._lock = lock or nullcontext()

    def append(self, result: WorkflowStepResult) -> WorkflowStepResult:
        payload = None if result.reading is None else json.dumps(result.reading.as_dict())
        with self._lock:
            cursor = self._con.execute(
                """
                INSERT INTO workflow_step_results (
                    run_id, step_id, step_index, completed_at, status, note, reading_json,
                    verdict, verdict_detail
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.run_id,
                    result.step_id,
                    result.step_index,
                    result.completed_at.isoformat(),
                    result.status.value,
                    result.note,
                    payload,
                    result.verdict.value,
                    result.verdict_detail,
                ),
            )
            self._con.commit()
        return WorkflowStepResult(
            run_id=result.run_id,
            step_id=result.step_id,
            step_index=result.step_index,
            completed_at=result.completed_at,
            status=result.status,
            note=result.note,
            reading=result.reading,
            verdict=result.verdict,
            verdict_detail=result.verdict_detail,
            result_id=cursor.lastrowid,
        )

    def list_for_run(self, run_id: str) -> list[WorkflowStepResult]:
        with self._lock:
            rows = self._con.execute(
                """
                SELECT * FROM workflow_step_results
                WHERE run_id = ?
                ORDER BY step_index ASC, completed_at ASC, id ASC
                """,
                (run_id,),
            ).fetchall()
        return [_result_from_row(row) for row in rows]


def _result_from_row(row: sqlite3.Row) -> WorkflowStepResult:
    reading = None if row["reading_json"] is None else _reading_from_json(row["reading_json"])
    keys = row.keys()
    verdict_raw = row["verdict"] if "verdict" in keys else None
    verdict_detail = row["verdict_detail"] if "verdict_detail" in keys else None
    return WorkflowStepResult(
        run_id=row["run_id"],
        step_id=row["step_id"],
        step_index=row["step_index"],
        completed_at=datetime.fromisoformat(row["completed_at"]),
        status=WorkflowStepResultStatus(row["status"]),
        note=row["note"],
        reading=reading,
        verdict=WorkflowVerdict(verdict_raw) if verdict_raw else WorkflowVerdict.NOT_EVALUATED,
        verdict_detail=verdict_detail,
        result_id=row["id"],
    )


def _reading_from_json(payload: str) -> Reading:
    data = json.loads(payload)
    return Reading(
        timestamp_utc=datetime.fromisoformat(data["timestamp_utc"]),
        value=data["value"],
        unit=data["unit"],
        measurement_type=MeasurementType(data["measurement_type"]),
        status=ReadingStatus(data["status"]),
        display_text=data["display_text"],
        source_device_id=data["source_device_id"],
        mode=data.get("mode", ""),
        metadata=dict(data.get("metadata", {})),
    )
