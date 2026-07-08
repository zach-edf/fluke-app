from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from fluke_app import ReportService, WorkflowRunner, new_session
from fluke_app.workflow_catalog import WorkflowCatalog
from fluke_core.enums import MeasurementType, ReadingStatus, WorkflowInteractionMode
from fluke_core.models.device import DeviceInfo
from fluke_core.models.reading import Reading
from fluke_core.models.workflow import (
    AcceptanceCriteria,
    RELATIVE_MODE_PERCENT_DROP,
    WorkflowDefinition,
    WorkflowStep,
)
from fluke_store import FlukeStore

try:
    import reportlab  # noqa: F401

    _HAS_REPORTLAB = True
except ModuleNotFoundError:  # pragma: no cover
    _HAS_REPORTLAB = False

try:
    from pypdf import PdfReader

    _HAS_PYPDF = True
except ModuleNotFoundError:  # pragma: no cover
    _HAS_PYPDF = False


def _catalog() -> WorkflowCatalog:
    return WorkflowCatalog(
        [
            WorkflowDefinition(
                workflow_id="drop_test",
                title="Voltage Drop Test",
                schema_version=2,
                steps=(
                    WorkflowStep(
                        step_id="safety",
                        title="Safety",
                        instruction="Confirm PPE.",
                        interaction_mode=WorkflowInteractionMode.MANUAL_CHECK,
                    ),
                    WorkflowStep(
                        step_id="no_load",
                        title="No Load Voltage",
                        instruction="Measure with no load.",
                        capture=True,
                        interaction_mode=WorkflowInteractionMode.STABLE_CAPTURE,
                        expected_measurement_type=MeasurementType.VOLTAGE_DC,
                        expected_unit="V",
                        acceptance=AcceptanceCriteria(min_value=100, max_value=140, unit="V"),
                    ),
                    WorkflowStep(
                        step_id="loaded",
                        title="Loaded Voltage",
                        instruction="Measure with load.",
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


def _reading(value: float, seconds: int) -> Reading:
    return Reading(
        timestamp_utc=datetime(2026, 7, 8, 12, 0, seconds, tzinfo=timezone.utc),
        value=value,
        unit="V",
        measurement_type=MeasurementType.VOLTAGE_DC,
        status=ReadingStatus.OK,
        display_text=f"{value:.1f} V",
        source_device_id="meter-1",
    )


def _device() -> DeviceInfo:
    return DeviceInfo(
        device_id="meter-1",
        ble_address="AA:BB:CC:DD:EE:FF",
        model_name="Fluke 376 FC",
        profile_id="fluke_376fc",
        serial_number="SN-REPORT-1",
        support_level="supported",
    )


@unittest.skipUnless(_HAS_REPORTLAB, "reportlab is required for PDF report tests")
class ReportServiceTests(unittest.TestCase):
    def _prepare_run(self, store: FlukeStore):
        store.upsert_device(_device())
        session = new_session(device_id="meter-1", title="Report Job", profile_id="fluke_376fc")
        store.sessions.create(session)
        runner = WorkflowRunner(_catalog(), store.workflow_runs, store.workflow_step_results)
        state = runner.start("drop_test", session.session_id)
        runner.complete_current_step(note="PPE on")
        runner.complete_current_step(latest_reading=_reading(120.0, 1), note="no load")
        state = runner.complete_current_step(latest_reading=_reading(108.0, 2), note="loaded")
        runner.set_report_meta(
            state.run.run_id,
            {
                "business_name": "Acme Electric",
                "customer_name": "Jane Doe",
                "site": "123 Main St",
                "job_number": "JOB-42",
                "technician": "Zach V",
            },
        )
        return state.run.run_id

    def _tmp_dir(self) -> Path:
        tmp = Path(__file__).resolve().parents[2] / ".test-tmp" / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)
        return tmp

    def test_render_workflow_report_produces_pdf(self) -> None:
        tmp = self._tmp_dir()
        store = FlukeStore(tmp / "report.db")
        try:
            run_id = self._prepare_run(store)
            service = ReportService(
                _catalog(),
                store.workflow_runs,
                store.workflow_step_results,
                store.sessions,
                store.devices,
            )
            out = Path(service.render_workflow_report(run_id, tmp / "job_report.pdf"))
            self.assertTrue(out.exists())
            # A non-trivial PDF: header, table, chart all present.
            self.assertGreater(out.stat().st_size, 2000)
            with out.open("rb") as handle:
                self.assertEqual(handle.read(5), b"%PDF-")
        finally:
            store.close()

    @unittest.skipUnless(_HAS_PYPDF, "pypdf is required to parse report text")
    def test_report_text_contains_job_details_and_verdict(self) -> None:
        tmp = self._tmp_dir()
        store = FlukeStore(tmp / "report.db")
        try:
            run_id = self._prepare_run(store)
            service = ReportService(
                _catalog(),
                store.workflow_runs,
                store.workflow_step_results,
                store.sessions,
                store.devices,
            )
            out = Path(service.render_workflow_report(run_id, tmp / "job_report.pdf"))
            text = " ".join((page.extract_text() or "") for page in PdfReader(str(out)).pages)
            for needle in ("Voltage Drop", "Acme Electric", "Jane Doe", "JOB-42", "SN-REPORT-1", "FAIL"):
                self.assertIn(needle, text)
        finally:
            store.close()

    def test_render_session_summary_produces_pdf(self) -> None:
        tmp = self._tmp_dir()
        store = FlukeStore(tmp / "report.db")
        try:
            store.upsert_device(_device())
            session = new_session(device_id="meter-1", title="Bench Session", profile_id="fluke_376fc")
            store.sessions.create(session)
            readings = [_reading(120.0, 1), _reading(119.0, 2), _reading(121.0, 3)]
            for reading in readings:
                store.add_reading(session.session_id, reading)
            service = ReportService(
                _catalog(), store.workflow_runs, store.workflow_step_results, store.sessions, store.devices
            )
            out = Path(service.render_session_summary(session.session_id, tmp / "session.pdf", readings))
            self.assertTrue(out.exists())
            self.assertGreater(out.stat().st_size, 1000)
        finally:
            store.close()


if __name__ == "__main__":
    unittest.main()
