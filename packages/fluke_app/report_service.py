"""Professional PDF report generation for workflow runs and sessions.

This is a shared application service so the desktop app, CLI, and SDK can all
produce the same job report. PDF rendering uses ``reportlab``, which is an
optional dependency shipped via the ``.[reports]`` extra. Importing this module
never requires reportlab; it is only imported when a PDF is actually rendered so
minimal installs keep working.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fluke_app.ports import (
    DeviceRepository,
    SessionRepository,
    WorkflowRunRepository,
    WorkflowStepResultRepository,
)
from fluke_app.workflow_catalog import WorkflowCatalog
from fluke_core.enums import WorkflowRunResult, WorkflowStepResultStatus, WorkflowVerdict
from fluke_core.models.device import DeviceInfo
from fluke_core.models.session import Session
from fluke_core.models.workflow import (
    WorkflowDefinition,
    WorkflowRun,
    WorkflowStep,
    WorkflowStepResult,
)

# Report-meta keys persisted with each run.
META_KEYS = (
    "business_name",
    "logo_path",
    "customer_name",
    "site",
    "job_number",
    "technician",
    "notes",
)


class ReportDependencyError(RuntimeError):
    """Raised when the optional reportlab dependency is unavailable."""


def _require_reportlab() -> Any:
    try:
        import reportlab  # noqa: F401
    except ModuleNotFoundError as exc:  # pragma: no cover - depends on environment
        raise ReportDependencyError(
            "PDF reports require the 'reportlab' package. Install it with "
            "`pip install -e \".[reports]\"` or `pip install reportlab`."
        ) from exc
    return reportlab


@dataclass(frozen=True, slots=True)
class ReportStepRow:
    index: int
    title: str
    instruction: str
    captured_value: float | None
    captured_text: str
    unit: str
    limits_text: str
    verdict: WorkflowVerdict
    verdict_detail: str
    status: WorkflowStepResultStatus | None
    note: str


@dataclass(frozen=True, slots=True)
class WorkflowReportContext:
    definition: WorkflowDefinition
    run: WorkflowRun
    session: Session | None
    device: DeviceInfo | None
    meta: dict[str, str]
    rows: tuple[ReportStepRow, ...]

    @property
    def title(self) -> str:
        return self.meta.get("report_title") or f"{self.definition.title} - Job Report"


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "-"
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _fmt_num(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.6g}"


def limits_text_for_step(step: WorkflowStep) -> str:
    criteria = step.acceptance
    if criteria is None or criteria.is_empty:
        return "-"
    parts: list[str] = []
    unit = criteria.unit or step.expected_unit or ""
    unit_suffix = f" {unit}" if unit else ""
    if criteria.min_value is not None:
        parts.append(f"min {_fmt_num(criteria.min_value)}{unit_suffix}")
    if criteria.max_value is not None:
        parts.append(f"max {_fmt_num(criteria.max_value)}{unit_suffix}")
    if criteria.has_relative:
        refs = list(criteria.reference_step_ids)
        if criteria.reference_step_id:
            refs.append(criteria.reference_step_id)
        ref_text = ", ".join(refs) if refs else "prior step"
        mode = (criteria.relative_mode or "").replace("_", " ")
        pct = "" if criteria.percent is None else f"{_fmt_num(criteria.percent)}% "
        parts.append(f"{pct}{mode} vs {ref_text}")
    return "; ".join(parts) if parts else "-"


def build_workflow_report_context(
    definition: WorkflowDefinition,
    run: WorkflowRun,
    results: list[WorkflowStepResult] | tuple[WorkflowStepResult, ...],
    session: Session | None,
    device: DeviceInfo | None,
    meta_overrides: dict[str, str] | None = None,
) -> WorkflowReportContext:
    meta = dict(run.report_meta)
    for key, value in (meta_overrides or {}).items():
        if value not in (None, ""):
            meta[str(key)] = str(value)

    results_by_step = {result.step_id: result for result in results}
    rows: list[ReportStepRow] = []
    for index, step in enumerate(definition.steps, start=1):
        result = results_by_step.get(step.step_id)
        reading = result.reading if result is not None else None
        captured_value = reading.value if reading is not None else None
        captured_text = "-"
        unit = step.expected_unit or ""
        if reading is not None:
            captured_text = reading.display_text or _fmt_num(reading.value)
            unit = reading.unit or unit
        rows.append(
            ReportStepRow(
                index=index,
                title=step.title,
                instruction=step.instruction,
                captured_value=captured_value,
                captured_text=captured_text,
                unit=unit,
                limits_text=limits_text_for_step(step),
                verdict=result.verdict if result is not None else WorkflowVerdict.NOT_EVALUATED,
                verdict_detail=(result.verdict_detail or "") if result is not None else "",
                status=result.status if result is not None else None,
                note=(result.note or "") if result is not None else "",
            )
        )
    return WorkflowReportContext(
        definition=definition,
        run=run,
        session=session,
        device=device,
        meta=meta,
        rows=tuple(rows),
    )


class ReportService:
    """Builds job report PDFs from persisted workflow runs and sessions."""

    def __init__(
        self,
        catalog: WorkflowCatalog,
        run_repo: WorkflowRunRepository,
        step_result_repo: WorkflowStepResultRepository,
        session_repo: SessionRepository | None = None,
        device_repo: DeviceRepository | None = None,
    ) -> None:
        self._catalog = catalog
        self._run_repo = run_repo
        self._step_result_repo = step_result_repo
        self._session_repo = session_repo
        self._device_repo = device_repo

    def workflow_report_context(
        self, run_id: str, meta_overrides: dict[str, str] | None = None
    ) -> WorkflowReportContext:
        run = self._run_repo.get(run_id)
        if run is None:
            raise RuntimeError(f"Unknown workflow run {run_id!r}.")
        definition = self._catalog.get(run.workflow_id)
        if definition is None:
            raise RuntimeError(f"Unknown workflow definition {run.workflow_id!r}.")
        results = self._step_result_repo.list_for_run(run_id)
        session = None
        if self._session_repo is not None:
            session = self._session_repo.get(run.session_id)
        device = None
        if self._device_repo is not None and session is not None:
            device = self._device_repo.get(session.device_id)
        return build_workflow_report_context(
            definition, run, results, session, device, meta_overrides
        )

    def render_workflow_report(
        self,
        run_id: str,
        path: str | Path,
        *,
        meta_overrides: dict[str, str] | None = None,
    ) -> str:
        context = self.workflow_report_context(run_id, meta_overrides)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _render_workflow_pdf(context, out_path)
        return str(out_path)

    def render_session_summary(
        self,
        session_id: str,
        path: str | Path,
        readings: list[Any] | None = None,
    ) -> str:
        if self._session_repo is None:
            raise RuntimeError("Session summary reports require a session repository.")
        session = self._session_repo.get(session_id)
        if session is None:
            raise RuntimeError(f"Unknown session {session_id!r}.")
        device = None
        if self._device_repo is not None:
            device = self._device_repo.get(session.device_id)
        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _render_session_pdf(session, device, readings or [], out_path)
        return str(out_path)


# ---------------------------------------------------------------------------
# PDF rendering (reportlab)
# ---------------------------------------------------------------------------

_VERDICT_COLORS = {
    WorkflowVerdict.PASS: "#1b7a34",
    WorkflowVerdict.FAIL: "#b3261e",
    WorkflowVerdict.NOT_EVALUATED: "#5f6368",
}


def _verdict_label(verdict: WorkflowVerdict) -> str:
    return {
        WorkflowVerdict.PASS: "PASS",
        WorkflowVerdict.FAIL: "FAIL",
        WorkflowVerdict.NOT_EVALUATED: "N/A",
    }[verdict]


def _render_workflow_pdf(context: WorkflowReportContext, path: Path) -> None:
    _require_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import (
        Image,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="CellWrap", parent=styles["Normal"], fontSize=7.5, leading=9))
    title_style = ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontSize=18, alignment=TA_LEFT, spaceAfter=2
    )

    story: list[Any] = []
    meta = context.meta
    run = context.run

    # Header with optional logo + business name.
    business = meta.get("business_name", "")
    logo_path = meta.get("logo_path", "")
    header_left: list[Any] = []
    if business:
        header_left.append(Paragraph(business, styles["Heading2"]))
    header_left.append(Paragraph(context.title, title_style))
    if logo_path and Path(logo_path).exists():
        try:
            logo = Image(logo_path, width=1.1 * inch, height=1.1 * inch, kind="proportional")
            header = Table([[header_left, logo]], colWidths=[5.2 * inch, 1.6 * inch])
            header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
            story.append(header)
        except Exception:
            story.extend(header_left)
    else:
        story.extend(header_left)

    story.append(Spacer(1, 6))

    overall = context.run.verdict
    verdict_para = Paragraph(
        f'<font color="{_VERDICT_COLORS[overall]}"><b>Overall result: '
        f"{_verdict_label(overall)}</b></font> "
        f"({run.result.value.replace('_', ' ').title()})",
        styles["Heading3"],
    )
    story.append(verdict_para)
    story.append(Spacer(1, 6))

    # Job / customer metadata block.
    session = context.session
    device = context.device
    info_rows = [
        ["Customer", meta.get("customer_name", "-"), "Technician", meta.get("technician", "-")],
        ["Site", meta.get("site", "-"), "Job #", meta.get("job_number", "-")],
        [
            "Date",
            _fmt_dt(run.started_at),
            "Device",
            _device_label(device),
        ],
        [
            "Serial",
            (device.serial_number if device and device.serial_number else "-"),
            "Session",
            (session.title if session and session.title else run.session_id),
        ],
    ]
    info = Table(info_rows, colWidths=[0.9 * inch, 2.5 * inch, 0.9 * inch, 2.5 * inch])
    info.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 8),
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 8),
                ("FONT", (2, 0), (2, -1), "Helvetica-Bold", 8),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#444444")),
                ("TEXTCOLOR", (2, 0), (2, -1), colors.HexColor("#444444")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
            ]
        )
    )
    story.append(info)
    story.append(Spacer(1, 10))

    # Per-step results table.
    story.append(Paragraph("Step Results", styles["Heading3"]))
    table_data: list[list[Any]] = [
        [
            Paragraph("<b>#</b>", styles["Small"]),
            Paragraph("<b>Step / Instruction</b>", styles["Small"]),
            Paragraph("<b>Reading</b>", styles["Small"]),
            Paragraph("<b>Limits</b>", styles["Small"]),
            Paragraph("<b>Result</b>", styles["Small"]),
            Paragraph("<b>Notes</b>", styles["Small"]),
        ]
    ]
    verdict_cell_styles: list[tuple[int, WorkflowVerdict]] = []
    for row in context.rows:
        step_cell = Paragraph(
            f"<b>{_esc(row.title)}</b><br/><font size=6>{_esc(row.instruction)}</font>",
            styles["CellWrap"],
        )
        reading_cell = Paragraph(_esc(row.captured_text), styles["CellWrap"])
        limits_cell = Paragraph(_esc(row.limits_text), styles["CellWrap"])
        note_text = row.note
        if row.verdict == WorkflowVerdict.FAIL and row.verdict_detail:
            note_text = (note_text + " " if note_text else "") + f"[{row.verdict_detail}]"
        note_cell = Paragraph(_esc(note_text), styles["CellWrap"])
        verdict_cell = Paragraph(
            f'<font color="{_VERDICT_COLORS[row.verdict]}"><b>{_verdict_label(row.verdict)}</b></font>',
            styles["CellWrap"],
        )
        table_data.append(
            [str(row.index), step_cell, reading_cell, limits_cell, verdict_cell, note_cell]
        )
        verdict_cell_styles.append((len(table_data) - 1, row.verdict))

    table = Table(
        table_data,
        colWidths=[0.3 * inch, 2.6 * inch, 1.0 * inch, 1.4 * inch, 0.6 * inch, 1.3 * inch],
        repeatRows=1,
    )
    style_commands = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2933")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fa")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    table.setStyle(TableStyle(style_commands))
    story.append(table)
    story.append(Spacer(1, 12))

    # Chart of numeric captured values, where meaningful.
    chart = _build_value_chart(context)
    if chart is not None:
        story.append(Paragraph("Captured Values", styles["Heading3"]))
        story.append(chart)
        story.append(Spacer(1, 8))

    if meta.get("notes"):
        story.append(Paragraph("Report Notes", styles["Heading3"]))
        story.append(Paragraph(_esc(meta["notes"]), styles["Normal"]))
        story.append(Spacer(1, 8))

    footer = Paragraph(
        f"<font size=7 color='#888888'>Generated {_fmt_dt(datetime.now(timezone.utc))} "
        f"&bull; Run {run.run_id} &bull; Workflow {run.workflow_id} "
        f"&bull; schema v{context.definition.schema_version}</font>",
        styles["Small"],
    )
    story.append(Spacer(1, 10))
    story.append(footer)

    doc = SimpleDocTemplate(
        str(path),
        pagesize=letter,
        title=context.title,
        author=meta.get("technician") or business or "Fluke Community",
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
    )
    doc.build(story)


def _build_value_chart(context: WorkflowReportContext) -> Any:
    numeric_rows = [row for row in context.rows if row.captured_value is not None]
    if len(numeric_rows) < 2:
        return None
    # Only chart when captured values share a comparable unit.
    units = {row.unit for row in numeric_rows if row.unit}
    if len(units) > 1:
        return None
    try:
        from reportlab.graphics.charts.barcharts import VerticalBarChart
        from reportlab.graphics.shapes import Drawing, String
        from reportlab.lib import colors
    except ModuleNotFoundError:  # pragma: no cover
        return None

    values = [float(row.captured_value) for row in numeric_rows]
    labels = [f"{row.index}" for row in numeric_rows]
    verdict_colors = [colors.HexColor(_VERDICT_COLORS[row.verdict]) for row in numeric_rows]

    drawing = Drawing(400, 180)
    chart = VerticalBarChart()
    chart.x = 30
    chart.y = 25
    chart.width = 340
    chart.height = 130
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.valueAxis.valueMin = min(0, min(values))
    chart.valueAxis.valueMax = max(values) * 1.15 if max(values) > 0 else 1
    chart.barWidth = 6
    chart.groupSpacing = 8
    for index, color in enumerate(verdict_colors):
        chart.bars[(0, index)].fillColor = color
    unit = next(iter(units), "")
    drawing.add(chart)
    drawing.add(String(30, 165, f"Captured value by step ({unit})".strip(), fontSize=8))
    return drawing


def _render_session_pdf(
    session: Session, device: DeviceInfo | None, readings: list[Any], path: Path
) -> None:
    _require_reportlab()
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    story: list[Any] = [Paragraph(session.title or "Session Summary", styles["Title"])]

    numeric = [r for r in readings if getattr(r, "value", None) is not None]
    values = [float(r.value) for r in numeric]
    stats_rows = [
        ["Session", session.session_id],
        ["Device", _device_label(device)],
        ["Started", _fmt_dt(session.started_at)],
        ["Ended", _fmt_dt(session.ended_at)],
        ["Readings", str(len(readings))],
        ["Numeric samples", str(len(numeric))],
        ["Min", _fmt_num(min(values)) if values else "-"],
        ["Max", _fmt_num(max(values)) if values else "-"],
        ["Average", _fmt_num(sum(values) / len(values)) if values else "-"],
    ]
    table = Table(stats_rows, colWidths=[1.5 * inch, 4.5 * inch])
    table.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (0, -1), "Helvetica-Bold", 9),
                ("FONT", (1, 0), (1, -1), "Helvetica", 9),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#dddddd")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(Spacer(1, 8))
    story.append(table)
    if session.notes:
        story.append(Spacer(1, 10))
        story.append(Paragraph("Notes", styles["Heading3"]))
        story.append(Paragraph(_esc(session.notes), styles["Normal"]))

    doc = SimpleDocTemplate(str(path), pagesize=letter, title=session.title or "Session Summary")
    doc.build(story)


def _device_label(device: DeviceInfo | None) -> str:
    if device is None:
        return "-"
    label = device.model_name or device.device_id
    return label


def _esc(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
