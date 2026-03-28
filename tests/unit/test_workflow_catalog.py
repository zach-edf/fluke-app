from __future__ import annotations

import unittest

from fluke_app.workflow_catalog import load_workflow_catalog
from fluke_core.enums import MeasurementType


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


if __name__ == "__main__":
    unittest.main()
