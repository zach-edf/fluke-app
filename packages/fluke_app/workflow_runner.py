from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from fluke_app.ports import WorkflowRunRepository, WorkflowStepResultRepository
from fluke_app.workflow_catalog import WorkflowCatalog
from fluke_core.enums import WorkflowRunResult, WorkflowStepResultStatus, WorkflowVerdict
from fluke_core.models.reading import Reading
from fluke_core.models.workflow import WorkflowRun, WorkflowRunState, WorkflowStep, WorkflowStepResult
from fluke_core.services.thresholds import combine_run_verdict, evaluate_step


class WorkflowRunner:
    def __init__(
        self,
        catalog: WorkflowCatalog,
        run_repo: WorkflowRunRepository,
        step_result_repo: WorkflowStepResultRepository,
    ) -> None:
        self._catalog = catalog
        self._run_repo = run_repo
        self._step_result_repo = step_result_repo
        self._active_run_id: str | None = None

    def set_catalog(self, catalog: WorkflowCatalog) -> None:
        """Swap the catalog after a reload so new/customized workflows are startable."""
        self._catalog = catalog

    def start(self, workflow_id: str, session_id: str, *, started_at: datetime | None = None) -> WorkflowRunState:
        active = self.active_state()
        if active is not None and not active.is_complete:
            raise RuntimeError("Finish or cancel the current workflow before starting another one.")
        definition = self._catalog.get(workflow_id)
        if definition is None:
            raise RuntimeError(f"Unknown workflow {workflow_id!r}.")
        run = WorkflowRun(
            run_id=uuid4().hex,
            workflow_id=workflow_id,
            session_id=session_id,
            started_at=started_at or datetime.now(timezone.utc),
            result=WorkflowRunResult.IN_PROGRESS,
            workflow_title=definition.title,
        )
        stored = self._run_repo.create(run)
        self._active_run_id = stored.run_id
        return WorkflowRunState(definition=definition, run=stored, completed_steps=())

    def active_state(self) -> WorkflowRunState | None:
        if self._active_run_id is None:
            return None
        run = self._run_repo.get(self._active_run_id)
        if run is None:
            self._active_run_id = None
            return None
        definition = self._catalog.get(run.workflow_id)
        if definition is None:
            self._active_run_id = None
            return None
        completed = tuple(self._step_result_repo.list_for_run(run.run_id))
        if run.result != WorkflowRunResult.IN_PROGRESS:
            self._active_run_id = None
        return WorkflowRunState(definition=definition, run=run, completed_steps=completed)

    def complete_current_step(
        self,
        *,
        latest_reading: Reading | None = None,
        note: str | None = None,
        completed_at: datetime | None = None,
    ) -> WorkflowRunState:
        state = self._require_active_state()
        step = state.current_step
        if step is None:
            raise RuntimeError("The active workflow is already complete.")

        reading = None
        status = WorkflowStepResultStatus.COMPLETED
        if step.requires_reading:
            reading = self.validate_reading_for_step(step, latest_reading)
            status = WorkflowStepResultStatus.CAPTURED
        elif step.is_capture_step and latest_reading is not None:
            # Legacy capture steps (capture=True without an explicit capture mode)
            # still record and evaluate the supplied reading.
            reading = latest_reading
            status = WorkflowStepResultStatus.CAPTURED

        verdict = WorkflowVerdict.NOT_EVALUATED
        verdict_detail: str | None = None
        if step.has_acceptance:
            reference_values = self._reference_values(state)
            value = reading.value if reading is not None else None
            evaluation = evaluate_step(step, value, reference_values)
            verdict = evaluation.verdict
            verdict_detail = evaluation.detail

        result = WorkflowStepResult(
            run_id=state.run.run_id,
            step_id=step.step_id,
            step_index=state.current_step_index,
            completed_at=completed_at or datetime.now(timezone.utc),
            status=status,
            note=note,
            reading=reading,
            verdict=verdict,
            verdict_detail=verdict_detail,
        )
        self._step_result_repo.append(result)
        return self._reload_and_finalize(state.run.run_id)

    def skip_current_step(self, note: str | None = None, *, completed_at: datetime | None = None) -> WorkflowRunState:
        state = self._require_active_state()
        step = state.current_step
        if step is None:
            raise RuntimeError("The active workflow is already complete.")
        result = WorkflowStepResult(
            run_id=state.run.run_id,
            step_id=step.step_id,
            step_index=state.current_step_index,
            completed_at=completed_at or datetime.now(timezone.utc),
            status=WorkflowStepResultStatus.SKIPPED,
            note=note,
            reading=None,
        )
        self._step_result_repo.append(result)
        return self._reload_and_finalize(state.run.run_id)

    def cancel(self, *, ended_at: datetime | None = None) -> WorkflowRun | None:
        state = self.active_state()
        if state is None:
            return None
        run = state.run
        run.ended_at = ended_at or datetime.now(timezone.utc)
        run.result = WorkflowRunResult.ABORTED
        stored = self._run_repo.update(run)
        self._active_run_id = None
        return stored

    def set_report_meta(self, run_id: str, meta: dict[str, str]) -> WorkflowRun | None:
        run = self._run_repo.get(run_id)
        if run is None:
            return None
        merged = dict(run.report_meta)
        for key, value in meta.items():
            if value is None or value == "":
                merged.pop(key, None)
            else:
                merged[key] = str(value)
        run.report_meta = merged
        return self._run_repo.update(run)

    def _reference_values(self, state: WorkflowRunState) -> dict[str, float | None]:
        values: dict[str, float | None] = {}
        for prior in state.completed_steps:
            if prior.reading is not None:
                values[prior.step_id] = prior.reading.value
        return values

    def list_recent_runs(self, limit: int = 10) -> list[WorkflowRun]:
        return self._run_repo.list_recent(limit=limit)

    def results_for_run(self, run_id: str) -> list[WorkflowStepResult]:
        return self._step_result_repo.list_for_run(run_id)

    def validate_reading_for_step(self, step: WorkflowStep, latest_reading: Reading | None) -> Reading:
        if latest_reading is None:
            raise RuntimeError("A live reading is required to capture this workflow step.")
        if (
            step.expected_measurement_type is not None
            and latest_reading.measurement_type != step.expected_measurement_type
        ):
            raise RuntimeError(
                f"Expected {step.expected_measurement_type.value} but received {latest_reading.measurement_type.value}."
            )
        if step.expected_unit is not None and latest_reading.unit != step.expected_unit:
            raise RuntimeError(f"Expected unit {step.expected_unit!r} but received {latest_reading.unit!r}.")
        return latest_reading

    def _require_active_state(self) -> WorkflowRunState:
        state = self.active_state()
        if state is None:
            raise RuntimeError("Start a workflow before capturing or completing steps.")
        return state

    def _reload_and_finalize(self, run_id: str) -> WorkflowRunState:
        run = self._run_repo.get(run_id)
        if run is None:
            raise RuntimeError(f"Unknown workflow run {run_id!r}.")
        definition = self._catalog.get(run.workflow_id)
        if definition is None:
            raise RuntimeError(f"Unknown workflow definition {run.workflow_id!r}.")
        completed = tuple(self._step_result_repo.list_for_run(run_id))
        run_verdict = combine_run_verdict([result.verdict for result in completed])
        if len(completed) >= len(definition.steps) and run.result == WorkflowRunResult.IN_PROGRESS:
            run.ended_at = completed[-1].completed_at if completed else datetime.now(timezone.utc)
            run.result = WorkflowRunResult.COMPLETED
            run.verdict = run_verdict
            run = self._run_repo.update(run)
            self._active_run_id = None
        elif run.verdict != run_verdict:
            run.verdict = run_verdict
            run = self._run_repo.update(run)
        return WorkflowRunState(definition=definition, run=run, completed_steps=completed)
