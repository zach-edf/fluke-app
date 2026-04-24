from __future__ import annotations

import json
from pathlib import Path
from importlib import resources

from fluke_core.enums import MeasurementType, WorkflowInteractionMode
from fluke_core.models.workflow import WorkflowCaptureSettings, WorkflowDefinition, WorkflowStep


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
    interaction_mode = _interaction_mode_from_payload(payload)
    raw_capture_settings = payload.get("capture_settings") or {}
    capture_settings = _capture_settings_from_payload(raw_capture_settings)
    capture = bool(payload.get("capture", False)) or interaction_mode in {
        WorkflowInteractionMode.STABLE_CAPTURE,
        WorkflowInteractionMode.COUNTDOWN_CAPTURE,
    }
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
        metadata=metadata,
    )


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
