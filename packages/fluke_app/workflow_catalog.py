from __future__ import annotations

import json
from pathlib import Path
from importlib import resources

from fluke_core.enums import MeasurementType, WorkflowInteractionMode
from fluke_core.models.workflow import (
    AcceptanceCriteria,
    RELATIVE_MODES,
    WORKFLOW_SCHEMA_VERSION,
    WorkflowCaptureSettings,
    WorkflowDefinition,
    WorkflowStep,
)


class WorkflowValidationError(ValueError):
    """Raised when a workflow definition fails schema validation."""


class WorkflowCatalog:
    def __init__(self, definitions: list[WorkflowDefinition]) -> None:
        seen: set[str] = set()
        ordered: list[WorkflowDefinition] = []
        for definition in definitions:
            if definition.workflow_id in seen:
                raise RuntimeError(f"Duplicate workflow id {definition.workflow_id!r}.")
            seen.add(definition.workflow_id)
            ordered.append(definition)
        self._definitions = {definition.workflow_id: definition for definition in ordered}

    def list(self) -> list[WorkflowDefinition]:
        return sorted(self._definitions.values(), key=lambda definition: definition.title.lower())

    def get(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._definitions.get(workflow_id)


def default_workflow_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "workflows"


def load_workflow_catalog(
    path: str | Path | None = None,
    *,
    extra_paths: list[str | Path] | tuple[str | Path, ...] = (),
) -> WorkflowCatalog:
    roots: list[Path] = []
    definitions: list[WorkflowDefinition] = []
    if path is None:
        definitions.extend(_load_builtin_definitions())
    else:
        roots.append(Path(path))
    roots.extend(Path(extra) for extra in extra_paths)
    for root in roots:
        if not root.exists():
            continue
        definitions.extend(_load_definition(file_path) for file_path in sorted(root.glob("*.json")))
    return WorkflowCatalog(definitions)


def _load_builtin_definitions() -> list[WorkflowDefinition]:
    try:
        root = resources.files("fluke_app.workflows")
    except ModuleNotFoundError:
        root_path = default_workflow_directory()
        if not root_path.exists():
            return []
        return [_load_definition(file_path) for file_path in sorted(root_path.glob("*.json"))]
    definitions: list[WorkflowDefinition] = []
    for item in sorted(root.iterdir(), key=lambda candidate: candidate.name):
        if item.name.endswith(".json"):
            definitions.append(_load_definition_from_text(item.read_text(encoding="utf-8")))
    return definitions


def _load_definition(path: Path) -> WorkflowDefinition:
    return _load_definition_from_text(path.read_text(encoding="utf-8"))


def _load_definition_from_text(text: str) -> WorkflowDefinition:
    payload = json.loads(text)
    steps = tuple(_step_from_payload(step) for step in payload.get("steps", []))
    raw_version = payload.get("schema_version")
    schema_version = 1 if raw_version in {None, ""} else int(raw_version)
    definition = WorkflowDefinition(
        workflow_id=payload["workflow_id"],
        title=payload["title"],
        description=payload.get("description", ""),
        category=payload.get("category", "General"),
        estimated_duration_min=payload.get("estimated_duration_min"),
        tags=tuple(payload.get("tags", ())),
        steps=steps,
        schema_version=schema_version,
    )
    validate_definition(definition)
    return definition


def validate_definition(definition: WorkflowDefinition) -> None:
    """Validate a workflow definition, raising WorkflowValidationError on problems."""

    if not definition.workflow_id:
        raise WorkflowValidationError("Workflow is missing a workflow_id.")
    if not definition.title:
        raise WorkflowValidationError(f"Workflow {definition.workflow_id!r} is missing a title.")
    if definition.schema_version > WORKFLOW_SCHEMA_VERSION:
        raise WorkflowValidationError(
            f"Workflow {definition.workflow_id!r} declares schema_version "
            f"{definition.schema_version}, newer than supported {WORKFLOW_SCHEMA_VERSION}."
        )
    seen_ids: set[str] = set()
    capture_ids: set[str] = set()
    for step in definition.steps:
        if not step.step_id:
            raise WorkflowValidationError(f"Workflow {definition.workflow_id!r} has a step without an id.")
        if step.step_id in seen_ids:
            raise WorkflowValidationError(
                f"Workflow {definition.workflow_id!r} has a duplicate step id {step.step_id!r}."
            )
        if not step.instruction:
            raise WorkflowValidationError(
                f"Step {step.step_id!r} in {definition.workflow_id!r} is missing an instruction."
            )
        _validate_acceptance(definition, step, seen_ids, capture_ids)
        seen_ids.add(step.step_id)
        if step.is_capture_step:
            capture_ids.add(step.step_id)


def _validate_acceptance(
    definition: WorkflowDefinition,
    step: WorkflowStep,
    prior_ids: set[str],
    prior_capture_ids: set[str],
) -> None:
    criteria = step.acceptance
    if criteria is None or criteria.is_empty:
        return
    if not step.is_capture_step:
        raise WorkflowValidationError(
            f"Step {step.step_id!r} in {definition.workflow_id!r} declares acceptance "
            "criteria but is not a capture step."
        )
    if criteria.min_value is not None and criteria.max_value is not None:
        if criteria.min_value > criteria.max_value:
            raise WorkflowValidationError(
                f"Step {step.step_id!r} in {definition.workflow_id!r} has min > max."
            )
    if not criteria.has_relative:
        return
    if criteria.relative_mode not in RELATIVE_MODES:
        raise WorkflowValidationError(
            f"Step {step.step_id!r} in {definition.workflow_id!r} uses unsupported "
            f"relative_mode {criteria.relative_mode!r}."
        )
    if criteria.percent is None:
        raise WorkflowValidationError(
            f"Step {step.step_id!r} in {definition.workflow_id!r} relative criterion "
            "is missing a percent value."
        )
    referenced = list(criteria.reference_step_ids)
    if criteria.reference_step_id:
        referenced.append(criteria.reference_step_id)
    if not referenced:
        raise WorkflowValidationError(
            f"Step {step.step_id!r} in {definition.workflow_id!r} relative criterion "
            "references no prior step."
        )
    for ref_id in referenced:
        if ref_id not in prior_capture_ids:
            raise WorkflowValidationError(
                f"Step {step.step_id!r} in {definition.workflow_id!r} references prior "
                f"capture step {ref_id!r} that does not exist earlier in the workflow."
            )


def _step_from_payload(payload: dict[str, object]) -> WorkflowStep:
    raw_measurement = payload.get("expected_measurement_type")
    measurement = None if raw_measurement in {None, ""} else MeasurementType(str(raw_measurement))
    raw_metadata = payload.get("metadata") or {}
    metadata = {str(key): str(value) for key, value in dict(raw_metadata).items()}
    interaction_mode = _interaction_mode_from_payload(payload)
    raw_capture_settings = payload.get("capture_settings") or {}
    capture_settings = _capture_settings_from_payload(raw_capture_settings)
    capture = bool(payload.get("capture", False)) or interaction_mode in {
        WorkflowInteractionMode.STABLE_CAPTURE,
        WorkflowInteractionMode.COUNTDOWN_CAPTURE,
    }
    acceptance = _acceptance_from_payload(payload.get("acceptance"))
    return WorkflowStep(
        step_id=str(payload["id"]),
        title=str(payload.get("title") or payload["id"]),
        instruction=str(payload["instruction"]),
        capture=capture,
        interaction_mode=interaction_mode,
        advance_on_capture=bool(payload.get("advance_on_capture", False)),
        capture_settings=capture_settings,
        expected_measurement_type=measurement,
        expected_unit=None if payload.get("expected_unit") in {None, ""} else str(payload["expected_unit"]),
        note_prompt=None if payload.get("note_prompt") in {None, ""} else str(payload["note_prompt"]),
        acceptance=acceptance,
        metadata=metadata,
    )


def _acceptance_from_payload(raw: object) -> AcceptanceCriteria | None:
    if not isinstance(raw, dict) or not raw:
        return None

    def _num(key: str) -> float | None:
        value = raw.get(key)
        return None if value in {None, ""} else float(value)

    reference_ids_raw = raw.get("reference_step_ids") or ()
    reference_ids = tuple(str(item) for item in reference_ids_raw if str(item))
    relative_mode_raw = raw.get("relative_mode")
    relative_mode = None if relative_mode_raw in {None, ""} else str(relative_mode_raw)
    criteria = AcceptanceCriteria(
        min_value=_num("min") if "min" in raw else _num("min_value"),
        max_value=_num("max") if "max" in raw else _num("max_value"),
        reference_step_id=None if raw.get("reference_step_id") in {None, ""} else str(raw["reference_step_id"]),
        reference_step_ids=reference_ids,
        relative_mode=relative_mode,
        percent=_num("percent"),
        unit=None if raw.get("unit") in {None, ""} else str(raw["unit"]),
        description=None if raw.get("description") in {None, ""} else str(raw["description"]),
    )
    return None if criteria.is_empty else criteria


def _interaction_mode_from_payload(payload: dict[str, object]) -> WorkflowInteractionMode:
    raw_mode = payload.get("interaction_mode")
    if raw_mode not in {None, ""}:
        return WorkflowInteractionMode(str(raw_mode))
    return WorkflowInteractionMode.STABLE_CAPTURE if bool(payload.get("capture", False)) else WorkflowInteractionMode.MANUAL_CHECK


def _capture_settings_from_payload(raw_settings: object) -> WorkflowCaptureSettings:
    settings = raw_settings if isinstance(raw_settings, dict) else {}
    absolute_raw = settings.get("absolute_tolerance")
    return WorkflowCaptureSettings(
        stable_for_s=float(settings.get("stable_for_s", 0.75)),
        min_samples=max(1, int(settings.get("min_samples", 5))),
        relative_tolerance=max(0.0, float(settings.get("relative_tolerance", 0.01))),
        absolute_tolerance=None if absolute_raw in {None, ""} else float(absolute_raw),
        countdown_s=max(0.0, float(settings.get("countdown_s", 3.0))),
    )
