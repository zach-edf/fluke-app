from __future__ import annotations

import json
from pathlib import Path
import unittest
from uuid import uuid4

from fluke_app.workflow_catalog import load_workflow_catalog
from fluke_core.enums import MeasurementType, WorkflowInteractionMode


class WorkflowCatalogTests(unittest.TestCase):
    def test_default_catalog_loads_example_workflows(self) -> None:
        catalog = load_workflow_catalog()
        workflows = catalog.list()

        self.assertEqual(len(workflows), 4)
        ids = {workflow.workflow_id for workflow in workflows}
        self.assertEqual(
            ids,
            {
                "battery_pack_check_v1",
                "charger_output_check_v1",
                "continuity_checklist_v1",
                "solar_panel_test_v1",
            },
        )

        battery = catalog.get("battery_pack_check_v1")
        self.assertIsNotNone(battery)
        self.assertEqual(len(battery.steps), 4)
        self.assertFalse(battery.steps[0].capture)
        self.assertTrue(battery.steps[1].capture)
        self.assertEqual(battery.steps[1].expected_measurement_type, MeasurementType.VOLTAGE_DC)

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
