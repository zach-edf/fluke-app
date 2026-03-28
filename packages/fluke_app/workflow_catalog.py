from __future__ import annotations

import json
from pathlib import Path

from fluke_core.enums import MeasurementType
from fluke_core.models.workflow import WorkflowDefinition, WorkflowStep


class WorkflowCatalog:
    def __init__(self, definitions: list[WorkflowDefinition]) -> None:
        self._definitions = {definition.workflow_id: definition for definition in definitions}

    def list(self) -> list[WorkflowDefinition]:
        return sorted(self._definitions.values(), key=lambda definition: definition.title.lower())

    def get(self, workflow_id: str) -> WorkflowDefinition | None:
        return self._definitions.get(workflow_id)


def default_workflow_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "workflows"


def load_workflow_catalog(path: str | Path | None = None) -> WorkflowCatalog:
    root = default_workflow_directory() if path is None else Path(path)
    definitions = [_load_definition(file_path) for file_path in sorted(root.glob("*.json"))]
    return WorkflowCatalog(definitions)


def _load_definition(path: Path) -> WorkflowDefinition:
    payload = json.loads(path.read_text(encoding="utf-8"))
    steps = tuple(_step_from_payload(step) for step in payload.get("steps", []))
    return WorkflowDefinition(
        workflow_id=payload["workflow_id"],
        title=payload["title"],
        description=payload.get("description", ""),
        category=payload.get("category", "General"),
        estimated_duration_min=payload.get("estimated_duration_min"),
        tags=tuple(payload.get("tags", ())),
        steps=steps,
    )


def _step_from_payload(payload: dict[str, object]) -> WorkflowStep:
    raw_measurement = payload.get("expected_measurement_type")
    measurement = None if raw_measurement in {None, ""} else MeasurementType(str(raw_measurement))
    raw_metadata = payload.get("metadata") or {}
    metadata = {str(key): str(value) for key, value in dict(raw_metadata).items()}
    return WorkflowStep(
        step_id=str(payload["id"]),
        title=str(payload.get("title") or payload["id"]),
        instruction=str(payload["instruction"]),
        capture=bool(payload.get("capture", False)),
        expected_measurement_type=measurement,
        expected_unit=None if payload.get("expected_unit") in {None, ""} else str(payload["expected_unit"]),
        note_prompt=None if payload.get("note_prompt") in {None, ""} else str(payload["note_prompt"]),
        metadata=metadata,
    )
