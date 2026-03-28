from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import sys
import zipfile

from fluke_app.workflow_catalog import WorkflowCatalog
from fluke_plugins.loader import PluginBundle
from fluke_protocol import ProfileRegistry
from fluke_store import FlukeStore


def export_debug_bundle(
    path: str | Path,
    *,
    profile_registry: ProfileRegistry,
    workflow_catalog: WorkflowCatalog,
    plugin_bundle: PluginBundle,
    database_path: str | Path | None = None,
) -> str:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    payloads: dict[str, str] = {
        "manifest.json": json.dumps(_manifest(database_path), indent=2, ensure_ascii=True),
        "profiles.json": json.dumps(_profiles_payload(profile_registry), indent=2, ensure_ascii=True),
        "workflows.json": json.dumps(_workflows_payload(workflow_catalog), indent=2, ensure_ascii=True),
        "plugins.json": json.dumps(_plugins_payload(plugin_bundle), indent=2, ensure_ascii=True),
    }
    if database_path is not None and Path(database_path).exists():
        payloads["store_snapshot.json"] = json.dumps(_store_snapshot(database_path), indent=2, ensure_ascii=True)

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for relative_path, text in payloads.items():
            bundle.writestr(relative_path, text)

    return str(target)


def _manifest(database_path: str | Path | None) -> dict[str, object]:
    return {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "python_version": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
            "machine": platform.machine(),
        },
        "database_path": None if database_path is None else str(Path(database_path)),
    }


def _profiles_payload(profile_registry: ProfileRegistry) -> list[dict[str, object]]:
    return [
        {
            "profile_id": profile.profile_id,
            "model_name": profile.model_name,
            "capabilities": profile.capabilities(),
            "notifications": profile.notification_characteristics(),
        }
        for profile in profile_registry.all()
    ]


def _workflows_payload(workflow_catalog: WorkflowCatalog) -> list[dict[str, object]]:
    return [
        {
            "workflow_id": workflow.workflow_id,
            "title": workflow.title,
            "category": workflow.category,
            "description": workflow.description,
            "estimated_duration_min": workflow.estimated_duration_min,
            "tags": list(workflow.tags),
            "steps": [
                {
                    "step_id": step.step_id,
                    "title": step.title,
                    "instruction": step.instruction,
                    "capture": step.capture,
                    "expected_measurement_type": None
                    if step.expected_measurement_type is None
                    else step.expected_measurement_type.value,
                    "expected_unit": step.expected_unit,
                    "note_prompt": step.note_prompt,
                }
                for step in workflow.steps
            ],
        }
        for workflow in workflow_catalog.list()
    ]


def _plugins_payload(plugin_bundle: PluginBundle) -> list[dict[str, object]]:
    return [
        {
            "plugin_id": plugin.manifest.plugin_id,
            "name": plugin.manifest.name,
            "version": plugin.manifest.version,
            "description": plugin.manifest.description,
            "root": str(plugin.root),
            "profiles": [profile.profile_id for profile in plugin.profiles],
            "workflow_paths": [str(path) for path in plugin.workflow_paths],
            "fixture_paths": [str(path) for path in plugin.fixture_paths],
        }
        for plugin in plugin_bundle.plugins
    ]


def _store_snapshot(database_path: str | Path) -> dict[str, object]:
    store = FlukeStore(database_path)
    try:
        snapshot = store.export_snapshot()
    finally:
        store.close()

    return {
        "devices": [
            {
                "device_id": device.device_id,
                "model_name": device.model_name,
                "profile_id": device.profile_id,
                "nickname": device.nickname,
                "support_level": device.support_level,
            }
            for device in snapshot["devices"]
        ],
        "sessions": [
            {
                "session_id": session.session_id,
                "device_id": session.device_id,
                "title": session.title,
                "started_at": session.started_at.isoformat(),
                "ended_at": None if session.ended_at is None else session.ended_at.isoformat(),
                "profile_id": session.profile_id,
            }
            for session in snapshot["sessions"]
        ],
        "markers": [
            {
                "session_id": marker.session_id,
                "timestamp_utc": marker.timestamp_utc.isoformat(),
                "label": marker.label,
                "note": marker.note,
            }
            for marker in snapshot["markers"]
        ],
        "workflow_runs": [
            {
                "run_id": run.run_id,
                "workflow_id": run.workflow_id,
                "session_id": run.session_id,
                "started_at": run.started_at.isoformat(),
                "ended_at": None if run.ended_at is None else run.ended_at.isoformat(),
                "result": run.result.value,
            }
            for run in snapshot["workflow_runs"]
        ],
    }
