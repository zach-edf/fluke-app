from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from fluke_core.enums import (
    MeasurementType,
    WorkflowInteractionMode,
    WorkflowRunResult,
    WorkflowStepResultStatus,
    WorkflowVerdict,
)
from fluke_core.models.reading import Reading

# Supported relative acceptance modes.
RELATIVE_MODE_PERCENT_WITHIN = "percent_within"
RELATIVE_MODE_PERCENT_OF_REFERENCE = "percent_of_reference"
RELATIVE_MODE_PERCENT_DROP = "percent_drop"
RELATIVE_MODE_MAX_UNBALANCE = "max_unbalance_percent"

RELATIVE_MODES = (
    RELATIVE_MODE_PERCENT_WITHIN,
    RELATIVE_MODE_PERCENT_OF_REFERENCE,
    RELATIVE_MODE_PERCENT_DROP,
    RELATIVE_MODE_MAX_UNBALANCE,
)


@dataclass(frozen=True, slots=True)
class WorkflowCaptureSettings:
    stable_for_s: float = 0.75
    min_samples: int = 5
    relative_tolerance: float = 0.01
    absolute_tolerance: float | None = None
    countdown_s: float = 3.0


@dataclass(frozen=True, slots=True)
class AcceptanceCriteria:
    """Pass/fail acceptance criteria for a capture step.

    Absolute criteria (``min_value`` / ``max_value``) and a relative criterion
    (referencing prior captured step values) may be combined. A step passes only
    if every declared criterion passes.
    """

    min_value: float | None = None
    max_value: float | None = None
    reference_step_id: str | None = None
    reference_step_ids: tuple[str, ...] = ()
    relative_mode: str | None = None
    percent: float | None = None
    unit: str | None = None
    description: str | None = None

    @property
    def has_absolute(self) -> bool:
        return self.min_value is not None or self.max_value is not None

    @property
    def has_relative(self) -> bool:
        return self.relative_mode is not None

    @property
    def is_empty(self) -> bool:
        return not self.has_absolute and not self.has_relative


@dataclass(frozen=True, slots=True)
class WorkflowStep:
    step_id: str
    title: str
    instruction: str
    capture: bool = False
    interaction_mode: WorkflowInteractionMode = WorkflowInteractionMode.MANUAL_CHECK
    advance_on_capture: bool = False
    capture_settings: WorkflowCaptureSettings = field(default_factory=WorkflowCaptureSettings)
    expected_measurement_type: MeasurementType | None = None
    expected_unit: str | None = None
    note_prompt: str | None = None
    acceptance: AcceptanceCriteria | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def has_acceptance(self) -> bool:
        return self.acceptance is not None and not self.acceptance.is_empty

    @property
    def requires_reading(self) -> bool:
        return self.interaction_mode in {
            WorkflowInteractionMode.STABLE_CAPTURE,
            WorkflowInteractionMode.COUNTDOWN_CAPTURE,
        }

    @property
    def is_capture_step(self) -> bool:
        return self.capture or self.requires_reading


# Current workflow JSON schema version. Bumped from the implicit v1 when
# pass/fail acceptance criteria were introduced. Older packs without a
# ``schema_version`` field are treated as v1 and still load unchanged.
WORKFLOW_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class WorkflowDefinition:
    workflow_id: str
    title: str
    description: str = ""
    category: str = "General"
    estimated_duration_min: int | None = None
    tags: tuple[str, ...] = ()
    steps: tuple[WorkflowStep, ...] = ()
    schema_version: int = 1

    @property
    def has_acceptance_criteria(self) -> bool:
        return any(step.has_acceptance for step in self.steps)


@dataclass(slots=True)
class WorkflowRun:
    run_id: str
    workflow_id: str
    session_id: str
    started_at: datetime
    ended_at: datetime | None = None
    result: WorkflowRunResult = WorkflowRunResult.IN_PROGRESS
    workflow_title: str | None = None
    verdict: WorkflowVerdict = WorkflowVerdict.NOT_EVALUATED
    report_meta: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowStepResult:
    run_id: str
    step_id: str
    step_index: int
    completed_at: datetime
    status: WorkflowStepResultStatus
    note: str | None = None
    reading: Reading | None = None
    verdict: WorkflowVerdict = WorkflowVerdict.NOT_EVALUATED
    verdict_detail: str | None = None
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
