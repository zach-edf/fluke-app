from __future__ import annotations

import json
import shutil
from pathlib import Path
from uuid import uuid4

import pytest

import fluke_app.workflow_catalog as workflow_catalog_module
from fluke_app.workflow_catalog import (
    load_workflow_catalog,
    save_workflow_definition,
    user_workflow_directory,
    workflow_definition_payload,
    _load_definition_from_text,
)

_TMP_ROOT = Path(__file__).resolve().parents[2] / ".test-tmp"


@pytest.fixture()
def tmp_dir() -> Path:
    target = _TMP_ROOT / f"workflow-customize-{uuid4().hex}"
    target.mkdir(parents=True, exist_ok=True)
    yield target
    shutil.rmtree(target, ignore_errors=True)


@pytest.fixture()
def user_dir(tmp_dir: Path, monkeypatch) -> Path:
    target = tmp_dir / "user-workflows"
    monkeypatch.setattr(workflow_catalog_module, "user_workflow_directory", lambda: target)
    return target


def _builtin_with_acceptance():
    catalog = load_workflow_catalog(include_user_directory=False)
    for definition in catalog.list():
        if definition.has_acceptance_criteria:
            return definition
    raise AssertionError("Expected at least one built-in workflow with acceptance criteria.")


class TestWorkflowSerializerRoundTrip:
    def test_payload_round_trips_including_acceptance(self) -> None:
        original = _builtin_with_acceptance()
        payload = workflow_definition_payload(original)
        reloaded = _load_definition_from_text(json.dumps(payload))

        assert reloaded.workflow_id == original.workflow_id
        assert reloaded.title == original.title
        assert reloaded.schema_version == original.schema_version
        assert len(reloaded.steps) == len(original.steps)
        for before, after in zip(original.steps, reloaded.steps):
            assert after.step_id == before.step_id
            assert after.capture == before.capture
            assert after.interaction_mode == before.interaction_mode
            if before.acceptance is None:
                assert after.acceptance is None
            else:
                assert after.acceptance is not None
                assert after.acceptance.min_value == before.acceptance.min_value
                assert after.acceptance.max_value == before.acceptance.max_value
                assert after.acceptance.relative_mode == before.acceptance.relative_mode
                assert after.acceptance.percent == before.acceptance.percent
                assert after.acceptance.reference_step_id == before.acceptance.reference_step_id
                assert after.acceptance.reference_step_ids == before.acceptance.reference_step_ids


class TestSaveWorkflowDefinition:
    def test_saves_into_user_directory(self, user_dir: Path) -> None:
        definition = _builtin_with_acceptance()
        path = save_workflow_definition(definition)
        assert path == user_dir / f"{definition.workflow_id}.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["workflow_id"] == definition.workflow_id

    def test_refuses_to_overwrite_without_flag(self, user_dir: Path) -> None:
        definition = _builtin_with_acceptance()
        save_workflow_definition(definition)
        with pytest.raises(FileExistsError):
            save_workflow_definition(definition)
        # overwrite=True replaces the file instead of raising
        save_workflow_definition(definition, overwrite=True)


class TestUserDirectoryOverride:
    def test_user_copy_overrides_builtin(self, user_dir: Path) -> None:
        definition = _builtin_with_acceptance()
        payload = workflow_definition_payload(definition)
        payload["title"] = "Customized Title"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / f"{definition.workflow_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        catalog = load_workflow_catalog()
        loaded = catalog.get(definition.workflow_id)
        assert loaded is not None
        assert loaded.title == "Customized Title"
        assert catalog.is_overridden(definition.workflow_id)
        # Total count unchanged: the copy replaces, it does not duplicate.
        baseline = load_workflow_catalog(include_user_directory=False)
        assert len(catalog.list()) == len(baseline.list())

    def test_user_directory_can_add_new_workflows(self, user_dir: Path) -> None:
        definition = _builtin_with_acceptance()
        payload = workflow_definition_payload(definition)
        payload["workflow_id"] = "my_custom_check_v1"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / "my_custom_check_v1.json").write_text(json.dumps(payload), encoding="utf-8")

        catalog = load_workflow_catalog()
        added = catalog.get("my_custom_check_v1")
        assert added is not None
        assert not catalog.is_overridden(definition.workflow_id)

    def test_include_user_directory_false_ignores_user_copies(self, user_dir: Path) -> None:
        definition = _builtin_with_acceptance()
        payload = workflow_definition_payload(definition)
        payload["title"] = "Customized Title"
        user_dir.mkdir(parents=True, exist_ok=True)
        (user_dir / f"{definition.workflow_id}.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

        catalog = load_workflow_catalog(include_user_directory=False)
        loaded = catalog.get(definition.workflow_id)
        assert loaded is not None
        assert loaded.title == definition.title

    def test_duplicate_ids_within_one_root_still_raise(self, user_dir: Path, tmp_dir: Path) -> None:
        definition = _builtin_with_acceptance()
        payload = workflow_definition_payload(definition)
        root = tmp_dir / "pack-root"
        root.mkdir()
        (root / "a.json").write_text(json.dumps(payload), encoding="utf-8")
        (root / "b.json").write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(RuntimeError, match="Duplicate workflow id"):
            load_workflow_catalog(root, include_user_directory=False)


class TestUserWorkflowDirectory:
    def test_resolves_under_user_data_dir(self) -> None:
        path = user_workflow_directory()
        assert path.name == "workflows"
        assert "fluke-community" in str(path)
