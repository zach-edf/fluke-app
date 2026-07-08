from __future__ import annotations

import json
from pathlib import Path
import unittest
from uuid import uuid4

from fluke_app.workflow_catalog import (
    WorkflowValidationError,
    load_workflow_catalog,
    validate_definition,
)
from fluke_core.enums import MeasurementType, WorkflowInteractionMode
from fluke_core.models.workflow import (
    RELATIVE_MODE_MAX_UNBALANCE,
    RELATIVE_MODE_PERCENT_DROP,
    RELATIVE_MODE_PERCENT_WITHIN,
    WORKFLOW_SCHEMA_VERSION,
)

_TRADE_PACK_IDS = {
    "motor_inrush_baseline_v1",
    "voltage_drop_under_load_v1",
    "three_phase_balance_survey_v1",
    "hvac_capacitor_check_v1",
    "hvac_amp_draw_v1",
    "evse_output_check_v1",
    "solar_string_voc_v1",
    "receptacle_branch_survey_v1",
}


class WorkflowCatalogTests(unittest.TestCase):
    def test_default_catalog_loads_all_builtin_workflows(self) -> None:
        catalog = load_workflow_catalog()
        workflows = catalog.list()

        ids = {workflow.workflow_id for workflow in workflows}
        # Original four packs remain present alongside the new trade packs.
        self.assertTrue(
            {
                "battery_pack_check_v1",
                "charger_output_check_v1",
                "continuity_checklist_v1",
                "solar_panel_test_v1",
            }.issubset(ids)
        )
        self.assertTrue(_TRADE_PACK_IDS.issubset(ids))

        battery = catalog.get("battery_pack_check_v1")
        self.assertIsNotNone(battery)
        self.assertEqual(len(battery.steps), 4)
        self.assertFalse(battery.steps[0].capture)
        self.assertTrue(battery.steps[1].capture)
        self.assertEqual(battery.steps[1].expected_measurement_type, MeasurementType.VOLTAGE_DC)

    def test_all_builtin_packs_validate(self) -> None:
        catalog = load_workflow_catalog()
        for definition in catalog.list():
            # Loading already validates; re-run explicitly for a clear assertion.
            validate_definition(definition)
            self.assertLessEqual(definition.schema_version, WORKFLOW_SCHEMA_VERSION)
            for step in definition.steps:
                self.assertTrue(step.step_id)
                self.assertTrue(step.instruction)

    def test_trade_packs_parse_acceptance_criteria(self) -> None:
        catalog = load_workflow_catalog()

        drop = catalog.get("voltage_drop_under_load_v1")
        loaded = next(s for s in drop.steps if s.step_id == "measure_loaded_voltage")
        self.assertTrue(loaded.has_acceptance)
        self.assertEqual(loaded.acceptance.relative_mode, RELATIVE_MODE_PERCENT_DROP)
        self.assertEqual(loaded.acceptance.reference_step_id, "measure_no_load_voltage")
        self.assertEqual(loaded.acceptance.percent, 5)

        cap = catalog.get("hvac_capacitor_check_v1")
        measure = next(s for s in cap.steps if s.step_id == "measure_capacitance")
        self.assertEqual(measure.acceptance.min_value, 42.3)
        self.assertEqual(measure.acceptance.max_value, 47.7)

        balance = catalog.get("three_phase_balance_survey_v1")
        l3 = next(s for s in balance.steps if s.step_id == "measure_l3_l1")
        self.assertEqual(l3.acceptance.relative_mode, RELATIVE_MODE_MAX_UNBALANCE)
        self.assertEqual(
            l3.acceptance.reference_step_ids, ("measure_l1_l2", "measure_l2_l3")
        )

        voc = catalog.get("solar_string_voc_v1")
        string_b = next(s for s in voc.steps if s.step_id == "measure_string_b_voc")
        self.assertEqual(string_b.acceptance.relative_mode, RELATIVE_MODE_PERCENT_WITHIN)

    def test_validation_rejects_relative_reference_to_missing_step(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)
        payload = {
            "workflow_id": "bad_ref",
            "title": "Bad Reference",
            "schema_version": 2,
            "steps": [
                {
                    "id": "measure",
                    "instruction": "Capture a value.",
                    "interaction_mode": "stable_capture",
                    "capture": True,
                    "expected_measurement_type": "voltage_dc",
                    "acceptance": {
                        "reference_step_id": "does_not_exist",
                        "relative_mode": "percent_within",
                        "percent": 5,
                    },
                }
            ],
        }
        (tmp / "bad_ref.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(WorkflowValidationError):
            load_workflow_catalog(tmp)

    def test_validation_rejects_min_greater_than_max(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)
        payload = {
            "workflow_id": "bad_limits",
            "title": "Bad Limits",
            "steps": [
                {
                    "id": "measure",
                    "instruction": "Capture a value.",
                    "interaction_mode": "stable_capture",
                    "capture": True,
                    "expected_measurement_type": "voltage_dc",
                    "acceptance": {"min": 100, "max": 10},
                }
            ],
        }
        (tmp / "bad_limits.json").write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaises(WorkflowValidationError):
            load_workflow_catalog(tmp)

    def test_legacy_pack_without_schema_version_defaults_to_v1(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)
        payload = {
            "workflow_id": "legacy_v1",
            "title": "Legacy",
            "steps": [
                {"id": "check", "instruction": "Confirm setup.", "capture": False}
            ],
        }
        (tmp / "legacy_v1.json").write_text(json.dumps(payload), encoding="utf-8")
        catalog = load_workflow_catalog(tmp)
        definition = catalog.get("legacy_v1")
        self.assertEqual(definition.schema_version, 1)
        self.assertFalse(definition.has_acceptance_criteria)

    def test_catalog_loads_interaction_modes_and_migrates_legacy_capture_steps(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        legacy_payload = {
            "workflow_id": "legacy_capture",
            "title": "Legacy Capture",
            "steps": [
                {
                    "id": "capture_voltage",
                    "instruction": "Capture the pack voltage.",
                    "capture": True,
                    "expected_measurement_type": "voltage_dc",
                    "expected_unit": "V",
                }
            ],
        }
        modern_payload = {
            "workflow_id": "modern_modes",
            "title": "Modern Modes",
            "steps": [
                {
                    "id": "countdown_current",
                    "title": "Countdown Capture",
                    "instruction": "Capture after a short delay.",
                    "interaction_mode": "countdown_capture",
                    "advance_on_capture": True,
                    "capture_settings": {
                        "countdown_s": 1.5,
                        "stable_for_s": 0.5,
                        "min_samples": 3,
                        "relative_tolerance": 0.02,
                    },
                    "expected_measurement_type": "current_ac",
                    "expected_unit": "A",
                },
                {
                    "id": "observe",
                    "instruction": "Observe the display and confirm.",
                    "interaction_mode": "observe_and_confirm",
                },
            ],
        }
        (tmp / "legacy_capture.json").write_text(json.dumps(legacy_payload), encoding="utf-8")
        (tmp / "modern_modes.json").write_text(json.dumps(modern_payload), encoding="utf-8")

        catalog = load_workflow_catalog(tmp)

        legacy = catalog.get("legacy_capture")
        self.assertIsNotNone(legacy)
        legacy_step = legacy.steps[0]
        self.assertTrue(legacy_step.capture)
        self.assertEqual(legacy_step.interaction_mode, WorkflowInteractionMode.STABLE_CAPTURE)
        self.assertFalse(legacy_step.advance_on_capture)
        self.assertEqual(legacy_step.capture_settings.stable_for_s, 0.75)
        self.assertEqual(legacy_step.capture_settings.min_samples, 5)

        modern = catalog.get("modern_modes")
        self.assertIsNotNone(modern)
        countdown_step = modern.steps[0]
        observe_step = modern.steps[1]
        self.assertEqual(countdown_step.interaction_mode, WorkflowInteractionMode.COUNTDOWN_CAPTURE)
        self.assertTrue(countdown_step.advance_on_capture)
        self.assertEqual(countdown_step.capture_settings.countdown_s, 1.5)
        self.assertEqual(countdown_step.capture_settings.min_samples, 3)
        self.assertEqual(observe_step.interaction_mode, WorkflowInteractionMode.OBSERVE_AND_CONFIRM)
        self.assertFalse(observe_step.requires_reading)


if __name__ == "__main__":
    unittest.main()
