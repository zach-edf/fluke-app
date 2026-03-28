from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fluke_core.enums import MeasurementType, WorkflowRunResult, WorkflowStepResultStatus
from fluke_core.models.reading import Reading


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    title: str
    instruction: str
    capture: bool = False
    expected_measurement_type: MeasurementType | None = None
    expected_unit: str | None = None
    note_prompt: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_id: str
    title: str
    description: str = ""
    category: str = "General"
    estimated_duration_min: int | None = None
    tags: tuple[str, ...] = ()
    steps: tuple[WorkflowStep, ...] = ()


@dataclass(slots=True)
class WorkflowRun:
    run_id: str
    workflow_id: str
    session_id: str
    started_at: datetime
    ended_at: datetime | None = None
    result: WorkflowRunResult = WorkflowRunResult.IN_PROGRESS
    workflow_title: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowStepResult:
    run_id: str
    step_id: str
    step_index: int
    completed_at: datetime
    status: WorkflowStepResultStatus
    note: str | None = None
    reading: Reading | None = None
    result_id: int | None = None


@dataclass(frozen=True, slots=True)
class WorkflowRunState:
    definition: WorkflowDefinition
    run: WorkflowRun
    completed_steps: tuple[WorkflowStepResult, ...] = ()

    @property
    def current_step_index(self) -> int:
        return min(len(self.completed_steps), len(self.definition.steps))

    @property
    def current_step(self) -> WorkflowStep | None:
        if self.current_step_index >= len(self.definition.steps):
            return None
        return self.definition.steps[self.current_step_index]

    @property
    def progress_text(self) -> str:
        return f"{min(len(self.completed_steps), len(self.definition.steps))}/{len(self.definition.steps)} steps"

    @property
    def is_complete(self) -> bool:
        return self.current_step is None or self.run.result == WorkflowRunResult.COMPLETED
