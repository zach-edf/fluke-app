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
    WorkflowVerdict,
)
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.workflow import (
    AcceptanceCriteria,
    RELATIVE_MODE_MAX_UNBALANCE,
    RELATIVE_MODE_PERCENT_DROP,
    RELATIVE_MODE_PERCENT_WITHIN,
    WorkflowCaptureSettings,
    WorkflowDefinition,
    WorkflowStep,
)
from fluke_core.services.thresholds import combine_run_verdict, evaluate_step
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


class ThresholdEvaluatorTests(unittest.TestCase):
    def _capture_step(self, acceptance: AcceptanceCriteria) -> WorkflowStep:
        return WorkflowStep(
            step_id="s",
            title="Capture",
            instruction="Capture.",
            capture=True,
            interaction_mode=WorkflowInteractionMode.STABLE_CAPTURE,
            expected_measurement_type=MeasurementType.VOLTAGE_DC,
            expected_unit="V",
            acceptance=acceptance,
        )

    def test_absolute_pass_and_fail(self) -> None:
        step = self._capture_step(AcceptanceCriteria(min_value=100, max_value=132, unit="V"))
        self.assertEqual(evaluate_step(step, 120).verdict, WorkflowVerdict.PASS)
        low = evaluate_step(step, 90)
        self.assertEqual(low.verdict, WorkflowVerdict.FAIL)
        self.assertIn("below min", low.detail)
        high = evaluate_step(step, 150)
        self.assertEqual(high.verdict, WorkflowVerdict.FAIL)
        self.assertIn("above max", high.detail)

    def test_no_criteria_is_not_evaluated(self) -> None:
        step = WorkflowStep(step_id="s", title="t", instruction="i", capture=True)
        self.assertEqual(evaluate_step(step, 120).verdict, WorkflowVerdict.NOT_EVALUATED)

    def test_none_value_is_not_evaluated(self) -> None:
        step = self._capture_step(AcceptanceCriteria(min_value=1))
        self.assertEqual(evaluate_step(step, None).verdict, WorkflowVerdict.NOT_EVALUATED)

    def test_percent_within_pass_and_fail(self) -> None:
        step = self._capture_step(
            AcceptanceCriteria(reference_step_id="ref", relative_mode=RELATIVE_MODE_PERCENT_WITHIN, percent=5)
        )
        self.assertEqual(evaluate_step(step, 104, {"ref": 100}).verdict, WorkflowVerdict.PASS)
        self.assertEqual(evaluate_step(step, 120, {"ref": 100}).verdict, WorkflowVerdict.FAIL)

    def test_percent_drop_pass_and_fail(self) -> None:
        step = self._capture_step(
            AcceptanceCriteria(reference_step_id="ref", relative_mode=RELATIVE_MODE_PERCENT_DROP, percent=5)
        )
        # A rise above reference is fine for a drop limit.
        self.assertEqual(evaluate_step(step, 121, {"ref": 120}).verdict, WorkflowVerdict.PASS)
        self.assertEqual(evaluate_step(step, 117, {"ref": 120}).verdict, WorkflowVerdict.PASS)
        fail = evaluate_step(step, 108, {"ref": 120})
        self.assertEqual(fail.verdict, WorkflowVerdict.FAIL)
        self.assertIn("dropped", fail.detail)

    def test_missing_reference_is_not_evaluated(self) -> None:
        step = self._capture_step(
            AcceptanceCriteria(reference_step_id="ref", relative_mode=RELATIVE_MODE_PERCENT_WITHIN, percent=5)
        )
        self.assertEqual(evaluate_step(step, 104, {}).verdict, WorkflowVerdict.NOT_EVALUATED)
        self.assertEqual(evaluate_step(step, 104, {"ref": None}).verdict, WorkflowVerdict.NOT_EVALUATED)

    def test_unbalance_pass_and_fail(self) -> None:
        step = self._capture_step(
            AcceptanceCriteria(
                reference_step_ids=("l1", "l2"),
                relative_mode=RELATIVE_MODE_MAX_UNBALANCE,
                percent=2,
            )
        )
        # 480/478/482 -> unbalance ~0.4% pass.
        self.assertEqual(evaluate_step(step, 482, {"l1": 480, "l2": 478}).verdict, WorkflowVerdict.PASS)
        # 480/460/500 -> unbalance ~4.2% fail.
        fail = evaluate_step(step, 500, {"l1": 480, "l2": 460})
        self.assertEqual(fail.verdict, WorkflowVerdict.FAIL)

    def test_combine_run_verdict(self) -> None:
        self.assertEqual(
            combine_run_verdict([WorkflowVerdict.PASS, WorkflowVerdict.FAIL]), WorkflowVerdict.FAIL
        )
        self.assertEqual(
            combine_run_verdict([WorkflowVerdict.PASS, WorkflowVerdict.NOT_EVALUATED]),
            WorkflowVerdict.PASS,
        )
        self.assertEqual(
            combine_run_verdict([WorkflowVerdict.NOT_EVALUATED]), WorkflowVerdict.NOT_EVALUATED
        )


class ThresholdRunnerIntegrationTests(unittest.TestCase):
    def _store(self) -> FlukeStore:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)
        store = FlukeStore(tmp / "thresholds.db")
        store.upsert_device(_device())
        session = new_session(device_id="meter-1", title="Threshold Session", profile_id="fluke_376fc")
        store.sessions.create(session)
        self._session_id = session.session_id
        return store

    def _catalog(self) -> WorkflowCatalog:
        return WorkflowCatalog(
            [
                WorkflowDefinition(
                    workflow_id="drop_test",
                    title="Drop Test",
                    schema_version=2,
                    steps=(
                        WorkflowStep(
                            step_id="no_load",
                            title="No Load",
                            instruction="Measure no load.",
                            capture=True,
                            interaction_mode=WorkflowInteractionMode.STABLE_CAPTURE,
                            expected_measurement_type=MeasurementType.VOLTAGE_DC,
                            expected_unit="V",
                            acceptance=AcceptanceCriteria(min_value=100, max_value=140, unit="V"),
                        ),
                        WorkflowStep(
                            step_id="loaded",
                            title="Loaded",
                            instruction="Measure loaded.",
                            capture=True,
                            interaction_mode=WorkflowInteractionMode.STABLE_CAPTURE,
                            expected_measurement_type=MeasurementType.VOLTAGE_DC,
                            expected_unit="V",
                            acceptance=AcceptanceCriteria(
                                reference_step_id="no_load",
                                relative_mode=RELATIVE_MODE_PERCENT_DROP,
                                percent=5,
                                unit="V",
                            ),
                        ),
                    ),
                )
            ]
        )

    def test_run_fails_when_relative_drop_exceeds_limit(self) -> None:
        store = self._store()
        try:
            runner = WorkflowRunner(self._catalog(), store.workflow_runs, store.workflow_step_results)
            runner.start("drop_test", self._session_id)
            runner.complete_current_step(latest_reading=_reading(120.0, seconds=1))
            state = runner.complete_current_step(latest_reading=_reading(108.0, seconds=2))
            self.assertEqual(state.run.result, WorkflowRunResult.COMPLETED)
            self.assertEqual(state.run.verdict, WorkflowVerdict.FAIL)
            results = runner.results_for_run(state.run.run_id)
            self.assertEqual(results[0].verdict, WorkflowVerdict.PASS)
            self.assertEqual(results[1].verdict, WorkflowVerdict.FAIL)
            self.assertIn("dropped", results[1].verdict_detail)
            # Verdicts survive a round-trip through persistence.
            reloaded = store.workflow_runs.get(state.run.run_id)
            self.assertEqual(reloaded.verdict, WorkflowVerdict.FAIL)
        finally:
            store.close()

    def test_run_passes_when_within_limits(self) -> None:
        store = self._store()
        try:
            runner = WorkflowRunner(self._catalog(), store.workflow_runs, store.workflow_step_results)
            runner.start("drop_test", self._session_id)
            runner.complete_current_step(latest_reading=_reading(120.0, seconds=1))
            state = runner.complete_current_step(latest_reading=_reading(118.0, seconds=2))
            self.assertEqual(state.run.verdict, WorkflowVerdict.PASS)
        finally:
            store.close()

    def test_report_meta_persists(self) -> None:
        store = self._store()
        try:
            runner = WorkflowRunner(self._catalog(), store.workflow_runs, store.workflow_step_results)
            state = runner.start("drop_test", self._session_id)
            runner.set_report_meta(state.run.run_id, {"customer_name": "Acme", "job_number": "J1"})
            reloaded = store.workflow_runs.get(state.run.run_id)
            self.assertEqual(reloaded.report_meta.get("customer_name"), "Acme")
            self.assertEqual(reloaded.report_meta.get("job_number"), "J1")
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
