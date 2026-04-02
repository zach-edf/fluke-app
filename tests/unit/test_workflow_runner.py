from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from fluke_app import WorkflowRunner, load_workflow_catalog, new_session
from fluke_app.workflow_catalog import WorkflowCatalog
from fluke_core.enums import (
    MeasurementType,
    ReadingStatus,
    WorkflowInteractionMode,
    WorkflowRunResult,
    WorkflowStepResultStatus,
)
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.workflow import WorkflowCaptureSettings, WorkflowDefinition, WorkflowStep
from fluke_store import FlukeStore


class WorkflowRunnerTests(unittest.TestCase):
    def test_runner_persists_steps_and_completes_workflow(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "workflow.db")
        try:
            store.upsert_device(_device())
            session = new_session(device_id="meter-1", title="Workflow Session", profile_id="fluke_376fc")
            store.sessions.create(session)
            runner = WorkflowRunner(load_workflow_catalog(), store.workflow_runs, store.workflow_step_results)

            state = runner.start("battery_pack_check_v1", session.session_id)
            self.assertEqual(state.progress_text, "0/4 steps")

            state = runner.complete_current_step(note="Meter set to DC voltage.")
            self.assertEqual(state.completed_steps[0].status, WorkflowStepResultStatus.COMPLETED)

            capture_1 = _reading(19.8, seconds=1)
            state = runner.complete_current_step(latest_reading=capture_1, note="Pack at rest.")
            self.assertEqual(state.completed_steps[1].status, WorkflowStepResultStatus.CAPTURED)
            self.assertEqual(state.completed_steps[1].reading.display_text, "19.8 V")

            capture_2 = _reading(18.9, seconds=3)
            state = runner.complete_current_step(latest_reading=capture_2, note="Loaded reading.")
            self.assertEqual(state.completed_steps[2].status, WorkflowStepResultStatus.CAPTURED)

            state = runner.complete_current_step(note="Pack voltage sag observed.")
            self.assertEqual(state.run.result, WorkflowRunResult.COMPLETED)
            self.assertIsNotNone(state.run.ended_at)

            recent = runner.list_recent_runs(limit=5)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0].workflow_id, "battery_pack_check_v1")

            persisted = runner.results_for_run(state.run.run_id)
            self.assertEqual(len(persisted), 4)
            self.assertEqual(persisted[1].reading.display_text, "19.8 V")
        finally:
            store.close()

    def test_runner_rejects_wrong_measurement_type_for_capture_step(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "workflow.db")
        try:
            store.upsert_device(_device())
            session = new_session(device_id="meter-1", title="Workflow Session", profile_id="fluke_376fc")
            store.sessions.create(session)
            runner = WorkflowRunner(load_workflow_catalog(), store.workflow_runs, store.workflow_step_results)

            runner.start("battery_pack_check_v1", session.session_id)
            runner.complete_current_step(note="Meter ready.")
            with self.assertRaises(RuntimeError):
                runner.complete_current_step(latest_reading=_current_reading(2.1))
        finally:
            store.close()

    def test_runner_uses_interaction_mode_to_decide_when_readings_are_required(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        store = FlukeStore(tmp / "workflow-modes.db")
        try:
            store.upsert_device(_device())
            session = new_session(device_id="meter-1", title="Workflow Session", profile_id="fluke_376fc")
            store.sessions.create(session)
            catalog = WorkflowCatalog(
                [
                    WorkflowDefinition(
                        workflow_id="mode_test",
                        title="Mode Test",
                        steps=(
                            WorkflowStep(
                                step_id="observe",
                                title="Observe",
                                instruction="Observe and confirm.",
                                interaction_mode=WorkflowInteractionMode.OBSERVE_AND_CONFIRM,
                            ),
                            WorkflowStep(
                                step_id="countdown",
                                title="Countdown",
                                instruction="Capture after a countdown.",
                                capture=True,
                                interaction_mode=WorkflowInteractionMode.COUNTDOWN_CAPTURE,
                                capture_settings=WorkflowCaptureSettings(countdown_s=1.0),
                                expected_measurement_type=MeasurementType.VOLTAGE_DC,
                                expected_unit="V",
                            ),
                        ),
                    )
                ]
            )
            runner = WorkflowRunner(catalog, store.workflow_runs, store.workflow_step_results)

            state = runner.start("mode_test", session.session_id)
            self.assertFalse(state.current_step.requires_reading)

            state = runner.complete_current_step(note="Confirmed visually.")
            self.assertEqual(state.completed_steps[0].status, WorkflowStepResultStatus.COMPLETED)
            self.assertTrue(state.current_step.requires_reading)

            state = runner.complete_current_step(latest_reading=_reading(13.2, seconds=2), note="Captured.")
            self.assertEqual(state.completed_steps[1].status, WorkflowStepResultStatus.CAPTURED)
            self.assertEqual(state.run.result, WorkflowRunResult.COMPLETED)
        finally:
            store.close()


def _reading(value: float, *, seconds: int) -> Reading:
    return Reading(
        timestamp_utc=datetime(2026, 3, 27, 12, 0, seconds, tzinfo=timezone.utc),
        value=value,
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_DC,
        status=ReadingStatus.OK,
        display_text=f"{value:.1f} V",
        source_device_id="meter-1",
    )


def _current_reading(value: float) -> Reading:
    return Reading(
        timestamp_utc=datetime(2026, 3, 27, 12, 0, 1, tzinfo=timezone.utc),
        value=value,
        unit="A",
        measurement_type=MeasurementType.CURRENT_DC,
        status=ReadingStatus.OK,
        display_text=f"{value:.1f} A",
        source_device_id="meter-1",
    )


def _device() -> DeviceInfo:
    return DeviceInfo(
        device_id="meter-1",
        ble_address="AA:BB:CC:DD:EE:FF",
        model_name="Fluke 376 FC",
        profile_id="fluke_376fc",
        nickname="Fluke 376 FC",
        support_level="supported",
    )


if __name__ == "__main__":
    unittest.main()
