from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from apps.desktop._qt import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QKeySequence,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QShortcut,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTimer,
    QVBoxLayout,
    QWidget,
    Qt,
)
from apps.desktop.widgets import build_reading_chart
from fluke_core.enums import MeasurementType, WorkflowInteractionMode
from fluke_core.models.workflow import WorkflowCaptureSettings, WorkflowDefinition, WorkflowStep


@dataclass(slots=True)
class _PanelRefs:
    panel: object
    refs: dict[str, object]


@dataclass(slots=True)
class _WorkflowStepDraft:
    title: str = ""
    instruction: str = ""
    capture: bool = False
    interaction_mode: WorkflowInteractionMode = WorkflowInteractionMode.MANUAL_CHECK
    advance_on_capture: bool = False
    expected_measurement_type: MeasurementType | None = None
    expected_unit: str = ""
    note_prompt: str = ""
    stable_for_s: float = 0.75
    min_samples: int = 5
    relative_tolerance: float = 0.01
    countdown_s: float = 3.0


# ---------------------------------------------------------------------------
# Table helpers
# ---------------------------------------------------------------------------

def _sync_table_rows(
    table: QTableWidget,
    rows: list[tuple[object, list[str]]],
) -> None:
    """Efficiently update a QTableWidget from a list of (row_id, [col_values])."""
    current = []
    for i in range(table.rowCount()):
        item0 = table.item(i, 0)
        row_id = item0.data(0x0100) if item0 else None
        cols = [table.item(i, c).text() if table.item(i, c) else "" for c in range(table.columnCount())]
        current.append((row_id, cols))

    new_data = [(rid, cols) for rid, cols in rows]
    if current == new_data:
        return

    table.setRowCount(len(rows))
    for i, (row_id, cols) in enumerate(rows):
        for c, text in enumerate(cols):
            item = QTableWidgetItem(text)
            if c == 0:
                item.setData(0x0100, row_id)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(i, c, item)


def _make_table(headers: list[str], min_height: int = 120) -> QTableWidget:
    """Create a styled QTableWidget with the given column headers."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
    table.setMinimumHeight(min_height)
    return table


def _selected_table_id(table: QTableWidget) -> object | None:
    """Return the row_id stored in column 0 of the currently selected row."""
    row = table.currentRow()
    if row < 0:
        return None
    item = table.item(row, 0)
    return item.data(0x0100) if item else None


def _sync_list_rows(list_widget, item_cls, rows: list[tuple[object, str]]) -> None:
    """Sync a QListWidget (used for simple lists like workflow catalog)."""
    current_rows = [
        (list_widget.item(index).data(0x0100), list_widget.item(index).text())
        for index in range(list_widget.count())
    ]
    if current_rows == rows:
        return
    list_widget.clear()
    for row_id, label in rows:
        item = item_cls(label)
        item.setData(0x0100, row_id)
        list_widget.addItem(item)


def _sync_combo_rows(combo: QComboBox, rows: list[tuple[object, str]], selected_id: object | None) -> None:
    """Sync a combo box from a list of (row_id, label) tuples."""
    current_rows = [(combo.itemData(index), combo.itemText(index)) for index in range(combo.count())]
    if current_rows == rows and combo.currentData() == selected_id:
        return

    combo.blockSignals(True)
    try:
        combo.clear()
        selected_index = 0
        for index, (row_id, label) in enumerate(rows):
            combo.addItem(label, row_id)
            if row_id == selected_id:
                selected_index = index
        combo.setCurrentIndex(selected_index if rows else -1)
    finally:
        combo.blockSignals(False)


# ---------------------------------------------------------------------------
# Confirmation helper
# ---------------------------------------------------------------------------

def _confirm(parent: QWidget, title: str, message: str) -> bool:
    """Show a Yes/No confirmation dialog. Returns True if user clicks Yes."""
    result = QMessageBox.question(
        parent, title, message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return result == QMessageBox.StandardButton.Yes


def _info(parent: QWidget, title: str, message: str) -> None:
    """Show an informational message dialog."""
    QMessageBox.information(parent, title, message)


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower())
    return slug.strip("_")


def _measurement_options() -> list[tuple[str, MeasurementType | None]]:
    return [("Any measurement", None)] + [
        (measurement.value.replace("_", " ").title(), measurement)
        for measurement in MeasurementType
        if measurement is not MeasurementType.UNKNOWN
    ]


def _interaction_mode_options() -> list[tuple[str, WorkflowInteractionMode]]:
    return [
        ("Manual Check", WorkflowInteractionMode.MANUAL_CHECK),
        ("Stable Capture", WorkflowInteractionMode.STABLE_CAPTURE),
        ("Countdown Capture", WorkflowInteractionMode.COUNTDOWN_CAPTURE),
        ("Observe And Confirm", WorkflowInteractionMode.OBSERVE_AND_CONFIRM),
    ]


def _coerce_measurement_type(value: object) -> MeasurementType | None:
    if value in {None, ""}:
        return None
    if isinstance(value, MeasurementType):
        return value
    return MeasurementType(str(value))


def _coerce_float(text: str, default: float) -> float:
    try:
        return float(text.strip())
    except ValueError:
        return default


class _WorkflowBuilderDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Workflow")
        self.resize(980, 720)

        self._step_drafts: list[_WorkflowStepDraft] = []
        self._workflow_id_dirty = False

        root = QVBoxLayout(self)

        form = QFormLayout()
        self._workflow_id = QLineEdit()
        self._workflow_id.setPlaceholderText("workflow_id")
        self._title = QLineEdit()
        self._title.setPlaceholderText("Solar Panel Test")
        self._description = QTextEdit()
        self._description.setFixedHeight(90)
        self._description.setPlaceholderText("Describe what this workflow guides the user through.")
        self._category = QLineEdit()
        self._category.setPlaceholderText("General")
        self._tags = QLineEdit()
        self._tags.setPlaceholderText("comma, separated, tags")
        self._duration = QSpinBox()
        self._duration.setRange(0, 1440)
        self._duration.setSpecialValueText("Unknown")
        self._duration.setSuffix(" min")
        form.addRow("Workflow ID", self._workflow_id)
        form.addRow("Title", self._title)
        form.addRow("Description", self._description)
        form.addRow("Category", self._category)
        form.addRow("Tags", self._tags)
        form.addRow("Estimated Duration", self._duration)
        root.addLayout(form)

        content = QHBoxLayout()

        step_column = QVBoxLayout()
        step_header = QLabel("Steps")
        step_header.setObjectName("section_header")
        step_column.addWidget(step_header)
        self._step_list = QListWidget()
        step_column.addWidget(self._step_list)

        step_actions = QHBoxLayout()
        self._add_step_button = QPushButton("Add Step")
        self._remove_step_button = QPushButton("Remove Step")
        self._move_up_button = QPushButton("Move Up")
        self._move_down_button = QPushButton("Move Down")
        for button in (
            self._add_step_button,
            self._remove_step_button,
            self._move_up_button,
            self._move_down_button,
        ):
            step_actions.addWidget(button)
        step_column.addLayout(step_actions)

        editor_column = QVBoxLayout()
        editor_header = QLabel("Step Details")
        editor_header.setObjectName("section_header")
        editor_column.addWidget(editor_header)

        editor_form = QFormLayout()
        self._step_title = QLineEdit()
        self._step_title.setPlaceholderText("Measure Open-Circuit Voltage")
        self._step_instruction = QTextEdit()
        self._step_instruction.setFixedHeight(120)
        self._step_instruction.setPlaceholderText("Explain exactly what the user should do.")
        self._step_mode = QComboBox()
        for label, value in _interaction_mode_options():
            self._step_mode.addItem(label, value)
        self._step_measurement = QComboBox()
        for label, value in _measurement_options():
            self._step_measurement.addItem(label, value)
        self._step_measurement.setToolTip("Available when this step is configured to capture a reading.")
        self._step_unit = QLineEdit()
        self._step_unit.setPlaceholderText("V")
        self._step_unit.setToolTip("Available when this step is configured to capture a reading.")
        self._step_advance = QCheckBox("Auto-advance after capture")
        self._step_stable_for = QLineEdit()
        self._step_stable_for.setPlaceholderText("0.75")
        self._step_relative_tolerance = QLineEdit()
        self._step_relative_tolerance.setPlaceholderText("0.01")
        self._step_min_samples = QSpinBox()
        self._step_min_samples.setRange(1, 200)
        self._step_countdown = QLineEdit()
        self._step_countdown.setPlaceholderText("3.0")
        self._step_note_prompt = QLineEdit()
        self._step_note_prompt.setPlaceholderText("Optional note prompt shown to the operator")
        editor_form.addRow("Title", self._step_title)
        editor_form.addRow("Instruction", self._step_instruction)
        editor_form.addRow("Interaction Mode", self._step_mode)
        editor_form.addRow("Measurement Type", self._step_measurement)
        editor_form.addRow("Expected Unit", self._step_unit)
        editor_form.addRow("", self._step_advance)
        editor_form.addRow("Stable For (s)", self._step_stable_for)
        editor_form.addRow("Min Samples", self._step_min_samples)
        editor_form.addRow("Rel Tolerance", self._step_relative_tolerance)
        editor_form.addRow("Countdown (s)", self._step_countdown)
        editor_form.addRow("Note Prompt", self._step_note_prompt)
        editor_column.addLayout(editor_form)
        editor_column.addStretch()

        content.addLayout(step_column, 2)
        content.addLayout(editor_column, 3)
        root.addLayout(content)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        save_button = self._buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button is not None:
            save_button.setText("Create Workflow")
            save_button.setObjectName("primary_button")
        cancel_button = self._buttons.button(QDialogButtonBox.StandardButton.Cancel)
        if cancel_button is not None:
            cancel_button.setText("Cancel")
        root.addWidget(self._buttons)

        self._title.textChanged.connect(self._sync_workflow_id_from_title)
        self._workflow_id.textEdited.connect(self._mark_workflow_id_dirty)
        self._step_list.currentRowChanged.connect(self._load_current_step)
        self._step_title.textChanged.connect(self._sync_current_step_fields)
        self._step_instruction.textChanged.connect(self._sync_current_step_fields)
        self._step_mode.currentIndexChanged.connect(self._update_capture_fields)
        self._step_mode.currentIndexChanged.connect(self._sync_current_step_fields)
        self._step_measurement.currentIndexChanged.connect(self._sync_current_step_fields)
        self._step_unit.textChanged.connect(self._sync_current_step_fields)
        self._step_advance.toggled.connect(self._sync_current_step_fields)
        self._step_stable_for.textChanged.connect(self._sync_current_step_fields)
        self._step_relative_tolerance.textChanged.connect(self._sync_current_step_fields)
        self._step_min_samples.valueChanged.connect(self._sync_current_step_fields)
        self._step_countdown.textChanged.connect(self._sync_current_step_fields)
        self._step_note_prompt.textChanged.connect(self._sync_current_step_fields)
        self._add_step_button.clicked.connect(self._add_step)
        self._remove_step_button.clicked.connect(self._remove_current_step)
        self._move_up_button.clicked.connect(self._move_current_step_up)
        self._move_down_button.clicked.connect(self._move_current_step_down)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        self._add_step()
        self._update_capture_fields()

    def accept(self) -> None:
        try:
            self.workflow_definition()
        except Exception as exc:
            QMessageBox.warning(self, "Invalid Workflow", str(exc))
            return
        super().accept()

    def workflow_definition(self) -> WorkflowDefinition:
        self._store_current_step()

        workflow_id = _slugify(self._workflow_id.text())
        if not workflow_id:
            raise RuntimeError("Enter a workflow ID.")

        title = self._title.text().strip()
        if not title:
            raise RuntimeError("Enter a workflow title.")

        category = self._category.text().strip() or "General"
        description = self._description.toPlainText().strip()
        tags = tuple(tag.strip() for tag in self._tags.text().split(",") if tag.strip())
        duration = self._duration.value() or None
        if not self._step_drafts:
            raise RuntimeError("Add at least one workflow step.")

        steps: list[WorkflowStep] = []
        used_step_ids: set[str] = set()
        for index, draft in enumerate(self._step_drafts, start=1):
            step_title = draft.title.strip()
            if not step_title:
                raise RuntimeError(f"Step {index} is missing a title.")
            instruction = draft.instruction.strip()
            if not instruction:
                raise RuntimeError(f"Step {index} is missing instructions.")

            base_step_id = _slugify(step_title) or f"step_{index}"
            step_id = base_step_id
            suffix = 2
            while step_id in used_step_ids:
                step_id = f"{base_step_id}_{suffix}"
                suffix += 1
            used_step_ids.add(step_id)

            steps.append(
                WorkflowStep(
                    step_id=step_id,
                    title=step_title,
                    instruction=instruction,
                    capture=draft.interaction_mode in {
                        WorkflowInteractionMode.STABLE_CAPTURE,
                        WorkflowInteractionMode.COUNTDOWN_CAPTURE,
                    },
                    interaction_mode=draft.interaction_mode,
                    advance_on_capture=draft.advance_on_capture,
                    capture_settings=WorkflowCaptureSettings(
                        stable_for_s=draft.stable_for_s,
                        min_samples=draft.min_samples,
                        relative_tolerance=draft.relative_tolerance,
                        countdown_s=draft.countdown_s,
                    ),
                    expected_measurement_type=(
                        draft.expected_measurement_type
                        if draft.interaction_mode in {
                            WorkflowInteractionMode.STABLE_CAPTURE,
                            WorkflowInteractionMode.COUNTDOWN_CAPTURE,
                        }
                        else None
                    ),
                    expected_unit=_text_or_none(draft.expected_unit) if draft.interaction_mode in {
                        WorkflowInteractionMode.STABLE_CAPTURE,
                        WorkflowInteractionMode.COUNTDOWN_CAPTURE,
                    } else None,
                    note_prompt=_text_or_none(draft.note_prompt),
                )
            )

        return WorkflowDefinition(
            workflow_id=workflow_id,
            title=title,
            description=description,
            category=category,
            estimated_duration_min=duration,
            tags=tags,
            steps=tuple(steps),
        )

    def _mark_workflow_id_dirty(self) -> None:
        self._workflow_id_dirty = True

    def _sync_workflow_id_from_title(self, text: str) -> None:
        if self._workflow_id_dirty:
            return
        suggestion = _slugify(text)
        self._workflow_id.setText("" if not suggestion else f"{suggestion}_v1")

    def _current_step_index(self) -> int:
        return self._step_list.currentRow()

    def _store_current_step(self) -> None:
        self._sync_current_step_fields()

    def _sync_current_step_fields(self) -> None:
        index = self._current_step_index()
        if not (0 <= index < len(self._step_drafts)):
            return
        self._step_drafts[index] = _WorkflowStepDraft(
            title=self._step_title.text().strip(),
            instruction=self._step_instruction.toPlainText().strip(),
            capture=self._step_mode.currentData() in {
                WorkflowInteractionMode.STABLE_CAPTURE,
                WorkflowInteractionMode.COUNTDOWN_CAPTURE,
            },
            interaction_mode=self._step_mode.currentData(),
            advance_on_capture=self._step_advance.isChecked(),
            expected_measurement_type=_coerce_measurement_type(self._step_measurement.currentData()),
            expected_unit=self._step_unit.text().strip(),
            note_prompt=self._step_note_prompt.text().strip(),
            stable_for_s=_coerce_float(self._step_stable_for.text(), 0.75),
            min_samples=self._step_min_samples.value(),
            relative_tolerance=_coerce_float(self._step_relative_tolerance.text(), 0.01),
            countdown_s=_coerce_float(self._step_countdown.text(), 3.0),
        )
        self._refresh_step_list_labels()

    def _load_current_step(self, index: int) -> None:
        if not (0 <= index < len(self._step_drafts)):
            self._set_step_editor_enabled(False)
            return
        draft = self._step_drafts[index]
        self._set_step_editor_enabled(True)
        self._step_title.setText(draft.title)
        self._step_instruction.setPlainText(draft.instruction)
        mode_index = self._step_mode.findData(draft.interaction_mode)
        self._step_mode.setCurrentIndex(0 if mode_index < 0 else mode_index)
        measurement_index = self._step_measurement.findData(draft.expected_measurement_type)
        self._step_measurement.setCurrentIndex(0 if measurement_index < 0 else measurement_index)
        self._step_unit.setText(draft.expected_unit)
        self._step_advance.setChecked(draft.advance_on_capture)
        self._step_stable_for.setText(str(draft.stable_for_s))
        self._step_relative_tolerance.setText(str(draft.relative_tolerance))
        self._step_min_samples.setValue(draft.min_samples)
        self._step_countdown.setText(str(draft.countdown_s))
        self._step_note_prompt.setText(draft.note_prompt)
        self._update_capture_fields()
        self._refresh_step_action_state()

    def _set_step_editor_enabled(self, enabled: bool) -> None:
        for widget in (
            self._step_title,
            self._step_instruction,
            self._step_mode,
            self._step_measurement,
            self._step_unit,
            self._step_advance,
            self._step_stable_for,
            self._step_relative_tolerance,
            self._step_min_samples,
            self._step_countdown,
            self._step_note_prompt,
        ):
            widget.setEnabled(enabled)
        self._refresh_step_action_state()

    def _refresh_step_action_state(self) -> None:
        index = self._current_step_index()
        has_selection = 0 <= index < len(self._step_drafts)
        self._remove_step_button.setEnabled(len(self._step_drafts) > 1 and has_selection)
        self._move_up_button.setEnabled(has_selection and index > 0)
        self._move_down_button.setEnabled(has_selection and index < len(self._step_drafts) - 1)

    def _refresh_step_list_labels(self) -> None:
        current_row = self._current_step_index()
        self._step_list.blockSignals(True)
        try:
            self._step_list.clear()
            for index, draft in enumerate(self._step_drafts, start=1):
                label = draft.title or f"Step {index}"
                label = f"{label} [{draft.interaction_mode.value.replace('_', ' ')}]"
                self._step_list.addItem(label)
            if self._step_drafts:
                next_row = min(max(current_row, 0), len(self._step_drafts) - 1)
                self._step_list.setCurrentRow(next_row)
        finally:
            self._step_list.blockSignals(False)
        self._refresh_step_action_state()

    def _add_step(self) -> None:
        self._store_current_step()
        next_index = len(self._step_drafts) + 1
        self._step_drafts.append(_WorkflowStepDraft(title=f"Step {next_index}"))
        self._refresh_step_list_labels()
        self._step_list.setCurrentRow(len(self._step_drafts) - 1)

    def _remove_current_step(self) -> None:
        index = self._current_step_index()
        if not (0 <= index < len(self._step_drafts)):
            return
        del self._step_drafts[index]
        self._refresh_step_list_labels()
        if self._step_drafts:
            next_index = min(index, len(self._step_drafts) - 1)
            self._step_list.setCurrentRow(next_index)
            self._load_current_step(next_index)

    def _move_current_step_up(self) -> None:
        index = self._current_step_index()
        if index <= 0:
            return
        self._store_current_step()
        self._step_drafts[index - 1], self._step_drafts[index] = self._step_drafts[index], self._step_drafts[index - 1]
        self._refresh_step_list_labels()
        self._step_list.setCurrentRow(index - 1)

    def _move_current_step_down(self) -> None:
        index = self._current_step_index()
        if not (0 <= index < len(self._step_drafts) - 1):
            return
        self._store_current_step()
        self._step_drafts[index + 1], self._step_drafts[index] = self._step_drafts[index], self._step_drafts[index + 1]
        self._refresh_step_list_labels()
        self._step_list.setCurrentRow(index + 1)

    def _update_capture_fields(self) -> None:
        mode = self._step_mode.currentData()
        capture_enabled = mode in {WorkflowInteractionMode.STABLE_CAPTURE, WorkflowInteractionMode.COUNTDOWN_CAPTURE}
        stable_enabled = mode == WorkflowInteractionMode.STABLE_CAPTURE
        countdown_enabled = mode == WorkflowInteractionMode.COUNTDOWN_CAPTURE
        self._step_measurement.setEnabled(capture_enabled)
        self._step_unit.setEnabled(capture_enabled)
        self._step_advance.setEnabled(capture_enabled)
        self._step_stable_for.setEnabled(stable_enabled)
        self._step_relative_tolerance.setEnabled(stable_enabled)
        self._step_min_samples.setEnabled(stable_enabled)
        self._step_countdown.setEnabled(countdown_enabled)


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

def create_main_window(runtime) -> QWidget:

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Fluke Community Desktop")
            self.setMinimumSize(900, 620)
            self.resize(1100, 760)

            root = QWidget()
            outer = QVBoxLayout(root)

            header = QHBoxLayout()
            title = QLabel("Fluke Community Desktop")
            title.setObjectName("section_header")
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            subtitle = QLabel("Connect, view, and log readings from supported meters.")
            subtitle.setWordWrap(True)
            header.addWidget(title, 2)
            header.addWidget(subtitle, 3)
            outer.addLayout(header)

            self._tabs = QTabWidget()
            self._home = _home_panel(self, runtime)
            self._discovery = _discovery_panel(self, runtime)
            self._live = _live_panel(self, runtime)
            self._session = _session_panel(self, runtime)
            self._workflow = _workflow_panel(self, runtime)
            self._settings = _settings_panel(self, runtime)
            self._tabs.addTab(self._home.panel, "Home")
            self._tabs.addTab(self._discovery.panel, "Device Discovery")
            self._tabs.addTab(self._live.panel, "Live Reading")
            self._tabs.addTab(self._session.panel, "Session")
            self._tabs.addTab(self._workflow.panel, "Workflows")
            self._tabs.addTab(self._settings.panel, "Settings")
            outer.addWidget(self._tabs)

            # Persistent status bar
            status_bar = QWidget()
            status_bar.setObjectName("status_bar")
            status_row = QHBoxLayout(status_bar)
            status_row.setContentsMargins(10, 4, 10, 4)
            self._sb_connection = QLabel("Disconnected")
            self._sb_session = QLabel("No active session")
            self._sb_reading = QLabel("Last reading: -")
            for lbl in (self._sb_connection, self._sb_session, self._sb_reading):
                lbl.setStyleSheet("font-size: 11px; color: #6B7280;")
            status_row.addWidget(self._sb_connection, 1)
            status_row.addWidget(self._sb_session, 1)
            status_row.addWidget(self._sb_reading, 1)
            outer.addWidget(status_bar)

            self.setCentralWidget(root)

            # Keyboard shortcuts
            for i in range(6):
                shortcut = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
                shortcut.activated.connect(lambda idx=i: self._tabs.setCurrentIndex(idx))

            QShortcut(QKeySequence("Ctrl+L"), self).activated.connect(
                lambda: _toggle_logging(runtime, self._live)
            )
            QShortcut(QKeySequence("Ctrl+M"), self).activated.connect(
                lambda: self._live.refs.get("marker_input") and self._live.refs["marker_input"].setFocus()
            )
            QShortcut(QKeySequence("Ctrl+E"), self).activated.connect(
                lambda: _export_and_notify(
                    self,
                    runtime,
                    lambda: runtime.presenter.export_session_csv(
                        _session_export_path(runtime, "csv"),
                        session_id=_selected_session_id(runtime),
                    ),
                    "CSV",
                )
            )
            QShortcut(QKeySequence(Qt.Key.Key_Space), self).activated.connect(
                lambda: _workflow_primary_shortcut(self, runtime)
            )
            QShortcut(QKeySequence(Qt.Key.Key_Return), self).activated.connect(
                lambda: _workflow_continue_shortcut(self, runtime)
            )
            QShortcut(QKeySequence(Qt.Key.Key_Enter), self).activated.connect(
                lambda: _workflow_continue_shortcut(self, runtime)
            )
            QShortcut(QKeySequence(Qt.Key.Key_R), self).activated.connect(
                lambda: _workflow_retake_shortcut(self, runtime)
            )
            QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(
                lambda: _workflow_cancel_shortcut(self, runtime)
            )

            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(250)
            self._refresh_timer.timeout.connect(self._refresh)
            self._refresh_timer.start()
            self._refresh()

        def closeEvent(self, event) -> None:  # type: ignore[override]
            self._refresh_timer.stop()
            try:
                _submit(runtime, runtime.presenter.disconnect_device())
            except Exception:
                pass
            super().closeEvent(event)

        def _refresh(self) -> None:
            _refresh_home(runtime, self._home)
            _refresh_discovery(runtime, self._discovery)
            _refresh_live(runtime, self._live)
            _refresh_session(runtime, self._session)
            _refresh_workflow(runtime, self._workflow)
            _refresh_settings(runtime, self._settings)
            # Status bar
            home = runtime.presenter.home_view_model()
            live = runtime.presenter.live_view_model()
            self._sb_connection.setText(home.connection_text)
            self._sb_session.setText(home.active_session_text)
            self._sb_reading.setText(f"Last reading: {live.last_updated_text}")

    return MainWindow()


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def _home_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    title = QLabel()
    subtitle = QLabel()
    connection_dot = QLabel("\u2B24")
    connection_dot.setFixedWidth(18)
    connection_dot.setStyleSheet("color: #9CA3AF; font-size: 11px;")
    connection = QLabel()
    connection_row = QHBoxLayout()
    connection_row.setContentsMargins(0, 0, 0, 0)
    connection_row.addWidget(connection_dot)
    connection_row.addWidget(connection, 1)
    device = QLabel()
    session = QLabel()
    message = QLabel()
    message.setWordWrap(True)

    recent_devices = _make_table(["Name", "Support", "Last Seen"], min_height=140)

    scan_button = QPushButton("Find Meters")
    scan_button.setObjectName("primary_button")
    scan_button.setToolTip("Scan for nearby BLE meters (Ctrl+1 then click)")
    reconnect_button = QPushButton("Reconnect Last Device")
    reconnect_button.setToolTip("Reconnect to the most recently used device")

    scan_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.scan_devices(timeout_s=5.0)))
    reconnect_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.reconnect_last_device()))

    for widget in (title, subtitle):
        layout.addWidget(widget)
    layout.addLayout(connection_row)
    for widget in (device, session, message, recent_devices):
        layout.addWidget(widget)
    btn_row = QHBoxLayout()
    btn_row.addWidget(scan_button)
    btn_row.addWidget(reconnect_button)
    layout.addLayout(btn_row)
    layout.addStretch()

    return _PanelRefs(
        panel=panel,
        refs={
            "title": title, "subtitle": subtitle,
            "connection_dot": connection_dot, "connection": connection,
            "device": device, "session": session, "message": message,
            "recent_devices": recent_devices,
            "scan_button": scan_button, "reconnect_button": reconnect_button,
        },
    )


def _discovery_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    description = QLabel("Scan for nearby meters and connect to a supported profile.")
    description.setWordWrap(True)
    status = QLabel()

    device_table = _make_table(["Name", "Model", "RSSI", "Support"])

    scan_button = QPushButton("Scan")
    scan_button.setObjectName("primary_button")
    scan_button.setToolTip("Scan for nearby BLE devices")
    connect_button = QPushButton("Connect")
    connect_button.setToolTip("Connect to the selected device")
    connect_button.setEnabled(False)

    def on_selection_changed() -> None:
        selected_id = _selected_table_id(device_table)
        runtime.presenter.select_device(selected_id)
        connect_button.setEnabled(selected_id is not None)

    def on_connect() -> None:
        selected_id = _selected_table_id(device_table)
        if selected_id is None:
            return
        _submit(runtime, runtime.presenter.connect_device(selected_id))

    device_table.itemSelectionChanged.connect(on_selection_changed)
    scan_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.scan_devices(timeout_s=5.0)))
    connect_button.clicked.connect(on_connect)

    for widget in (description, status, device_table):
        layout.addWidget(widget)
    btn_row = QHBoxLayout()
    btn_row.addWidget(scan_button)
    btn_row.addWidget(connect_button)
    layout.addLayout(btn_row)
    layout.addStretch()

    return _PanelRefs(
        panel=panel,
        refs={
            "status": status, "device_table": device_table,
            "scan_button": scan_button, "connect_button": connect_button,
        },
    )


def _live_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    value = QLabel()
    value.setObjectName("big_reading")
    unit = QLabel()
    measurement = QLabel()
    status = QLabel()
    connection_dot = QLabel("\u2B24")
    connection_dot.setFixedWidth(18)
    connection_dot.setStyleSheet("color: #9CA3AF; font-size: 11px;")
    connection = QLabel()
    connection_row = QHBoxLayout()
    connection_row.setContentsMargins(0, 0, 0, 0)
    connection_row.addWidget(connection_dot)
    connection_row.addWidget(connection, 1)
    chart_notice = QLabel()
    chart_notice.setObjectName("notice_banner")
    chart_notice.setWordWrap(True)
    chart_notice.hide()
    chart_mode = QComboBox()
    chart_mode.addItem("Rolling 30s", "rolling_30s")
    chart_mode.addItem("Rolling 60s", "rolling_60s")
    chart_mode.addItem("Rolling 5m", "rolling_5m")
    chart_mode.addItem("Since Mode Start", "since_mode_start")
    chart_mode.addItem("Since Session Start", "since_session_start")
    last_updated = QLabel()
    session = QLabel()
    summary = QLabel()
    marker_count = QLabel()
    alert_status = QLabel()
    alert_status.setWordWrap(True)
    alert_status.setObjectName("alert_status")
    chart = build_reading_chart(
        title="Live Reading",
        empty_text="Connect to a supported meter to start plotting live data.",
    )
    title_input = QLineEdit()
    notes_input = QTextEdit()
    notes_input.setFixedHeight(80)
    alert_banner = QLabel()
    alert_banner.setObjectName("alert_banner")
    alert_banner.setWordWrap(True)
    alert_banner.hide()
    alert_low_input = QLineEdit()
    alert_low_input.setPlaceholderText("Low threshold")
    alert_low_input.setFixedWidth(120)
    alert_high_input = QLineEdit()
    alert_high_input.setPlaceholderText("High threshold")
    alert_high_input.setFixedWidth(120)
    alert_apply_button = QPushButton("Set Alerts")
    alert_apply_button.setToolTip("Set value alert thresholds (leave blank to disable)")
    alert_clear_button = QPushButton("Clear")
    alert_clear_button.setToolTip("Remove all alert thresholds")

    def _apply_alerts() -> None:
        low_text = alert_low_input.text().strip()
        high_text = alert_high_input.text().strip()
        try:
            low = float(low_text) if low_text else None
            high = float(high_text) if high_text else None
        except ValueError:
            runtime.presenter.set_alert_configuration_error("thresholds must be numeric values.")
            return
        runtime.presenter.set_alert_thresholds(low, high)

    alert_apply_button.clicked.connect(lambda: _safe_call(runtime, _apply_alerts))
    alert_clear_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: (
            runtime.presenter.set_alert_thresholds(None, None),
            alert_low_input.clear(),
            alert_high_input.clear(),
        ))
    )

    marker_input = QLineEdit()
    marker_input.setPlaceholderText("Add a marker note during logging")

    start_button = QPushButton("Start Logging")
    start_button.setObjectName("primary_button")
    start_button.setToolTip("Begin recording readings to the database (Ctrl+L)")
    stop_button = QPushButton("Stop Logging")
    stop_button.setToolTip("Stop the current recording session (Ctrl+L)")
    add_marker_button = QPushButton("Add Marker")
    add_marker_button.setToolTip("Add a timestamped annotation to the session (Ctrl+M)")
    export_chart_button = QPushButton("Export Live Chart")
    export_chart_button.setToolTip("Save the current chart as a PNG image")
    disconnect_button = QPushButton("Disconnect")
    disconnect_button.setObjectName("danger_button")
    disconnect_button.setToolTip("Disconnect from the current BLE device")

    form = QFormLayout()
    form.addRow("Session Title", title_input)
    form.addRow("Session Notes", notes_input)
    form.addRow("Chart Mode", chart_mode)

    start_button.clicked.connect(
        lambda: _safe_call(
            runtime,
            lambda: runtime.presenter.start_logging(
                title=_text_or_none(title_input.text()),
                notes=_text_or_none(notes_input.toPlainText()),
            ),
        )
    )
    stop_button.clicked.connect(lambda: _safe_call(runtime, runtime.presenter.stop_logging))
    add_marker_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: _add_live_marker(runtime, marker_input))
    )
    export_chart_button.clicked.connect(
        lambda: _export_chart_with_dialog(window, runtime, chart, _live_chart_export_path(runtime))
    )
    disconnect_button.clicked.connect(
        lambda: _confirm_and_disconnect(window, runtime)
    )
    chart_mode.currentIndexChanged.connect(
        lambda: _safe_call(runtime, lambda: runtime.presenter.select_live_chart_mode(chart_mode.currentData()))
    )

    action_row = QHBoxLayout()
    action_row.addWidget(start_button)
    action_row.addWidget(stop_button)
    action_row.addWidget(export_chart_button)
    action_row.addWidget(disconnect_button)

    alert_row = QHBoxLayout()
    alert_row.addWidget(QLabel("Low:"))
    alert_row.addWidget(alert_low_input)
    alert_row.addWidget(QLabel("High:"))
    alert_row.addWidget(alert_high_input)
    alert_row.addWidget(alert_apply_button)
    alert_row.addWidget(alert_clear_button)
    alert_row.addStretch()

    marker_row = QHBoxLayout()
    marker_row.addWidget(marker_input, 1)
    marker_row.addWidget(add_marker_button)

    for widget in (value, unit, measurement, status):
        layout.addWidget(widget)
    layout.addLayout(connection_row)
    for widget in (chart_notice, alert_banner, alert_status, session, last_updated, summary, marker_count):
        layout.addWidget(widget)
    layout.addWidget(chart.widget, 1)
    layout.addLayout(alert_row)
    layout.addLayout(form)
    layout.addLayout(marker_row)
    layout.addLayout(action_row)

    scroll = QScrollArea()
    scroll.setWidget(panel)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.Shape.NoFrame)

    return _PanelRefs(
        panel=scroll,
        refs={
            "value": value, "unit": unit, "measurement": measurement,
            "status": status, "connection_dot": connection_dot, "connection": connection,
            "chart_notice": chart_notice, "alert_banner": alert_banner, "session": session,
            "alert_status": alert_status, "last_updated": last_updated, "summary": summary,
            "marker_count": marker_count, "title_input": title_input,
            "marker_input": marker_input,
            "start_button": start_button, "stop_button": stop_button,
            "add_marker_button": add_marker_button,
            "export_chart_button": export_chart_button,
            "disconnect_button": disconnect_button,
            "chart": chart,
            "chart_mode": chart_mode,
            "last_alert_event_id": 0,
        },
    )


def _session_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    active = QLabel()
    count = QLabel()
    summary = QLabel()
    compare_summary = QLabel()
    compare_summary.setWordWrap(True)
    database = QLabel()
    database.setWordWrap(True)
    export_status = QLabel()
    export_status.setWordWrap(True)
    context_filter = QComboBox()
    context_filter.setToolTip("Filter replay chart and summary by measurement context")
    axis_filter = QComboBox()
    axis_filter.addItem("Elapsed Time", "elapsed")
    axis_filter.addItem("UTC Timestamp", "utc")
    axis_filter.addItem("By Segment", "by_segment")
    axis_filter.setToolTip("Change the replay x-axis interpretation")
    segment_filter = QComboBox()
    segment_filter.setToolTip("Select a derived segment when using segment view")
    compare_filter = QComboBox()
    compare_filter.setToolTip("Overlay another session using the current measurement view")

    recent = _make_table(["Title", "Started", "Ended"], min_height=150)
    markers_table = _make_table(["Time", "Label", "Note"], min_height=100)

    notes = QTextEdit()
    notes.setReadOnly(True)
    notes.setFixedHeight(90)
    notes.setPlaceholderText("No notes recorded for this session.")
    chart = build_reading_chart(
        title="Session Replay",
        empty_text="Select a recorded session to inspect its replay chart and markers.",
    )
    export_csv = QPushButton("Export Raw CSV")
    export_csv.setToolTip("Export the selected session as raw CSV (Ctrl+E)")
    export_json = QPushButton("Export Raw JSON")
    export_json.setToolTip("Export the selected session as raw JSON")
    export_analysis = QPushButton("Export Analysis CSV")
    export_analysis.setToolTip("Export the selected session as a wide analysis table")
    export_segments = QPushButton("Export Segment Summary JSON")
    export_segments.setToolTip("Export the selected session's derived mode segments and marker summary")
    export_chart = QPushButton("Export Session Chart")
    export_chart.setToolTip("Save the session chart as a PNG image")

    def on_selection_changed() -> None:
        selected_id = _selected_table_id(recent)
        if selected_id is None:
            return
        _safe_call(runtime, lambda: runtime.presenter.select_session(selected_id))

    def on_context_changed() -> None:
        _safe_call(runtime, lambda: runtime.presenter.select_session_context(context_filter.currentData()))

    def on_compare_changed() -> None:
        _safe_call(runtime, lambda: runtime.presenter.select_compare_session(compare_filter.currentData()))

    def on_axis_changed() -> None:
        _safe_call(runtime, lambda: runtime.presenter.select_session_axis_mode(axis_filter.currentData()))

    def on_segment_changed() -> None:
        _safe_call(runtime, lambda: runtime.presenter.select_session_segment(segment_filter.currentData()))

    export_csv.clicked.connect(
        lambda: _export_and_notify(
            window, runtime,
            lambda: runtime.presenter.export_session_csv(
                _session_export_path(runtime, "csv"),
                session_id=_selected_session_id(runtime),
            ),
            "CSV",
        )
    )
    export_json.clicked.connect(
        lambda: _export_and_notify(
            window, runtime,
            lambda: runtime.presenter.export_session_json(
                _session_export_path(runtime, "json"),
                session_id=_selected_session_id(runtime),
            ),
            "JSON",
        )
    )
    export_chart.clicked.connect(
        lambda: _export_chart_with_dialog(window, runtime, chart, _session_chart_export_path(runtime))
    )
    export_analysis.clicked.connect(
        lambda: _export_and_notify(
            window,
            runtime,
            lambda: runtime.presenter.export_analysis_csv(
                _session_export_path(runtime, "analysis.csv"),
                session_id=_selected_session_id(runtime),
            ),
            "Analysis CSV",
        )
    )
    export_segments.clicked.connect(
        lambda: _export_and_notify(
            window,
            runtime,
            lambda: runtime.presenter.export_segment_summary_json(
                _session_export_path(runtime, "segments.json"),
                session_id=_selected_session_id(runtime),
            ),
            "Segment Summary JSON",
        )
    )
    recent.itemSelectionChanged.connect(on_selection_changed)
    context_filter.currentIndexChanged.connect(on_context_changed)
    axis_filter.currentIndexChanged.connect(on_axis_changed)
    segment_filter.currentIndexChanged.connect(on_segment_changed)
    compare_filter.currentIndexChanged.connect(on_compare_changed)

    session_list_column = QVBoxLayout()
    header = QLabel("Recent Sessions")
    header.setObjectName("section_header")
    session_list_column.addWidget(header)
    session_list_column.addWidget(recent)

    detail_column = QVBoxLayout()
    for widget in (active, count, summary, compare_summary, database, export_status):
        detail_column.addWidget(widget)
    context_row = QHBoxLayout()
    context_label = QLabel("Measurement View")
    context_label.setObjectName("section_header")
    context_row.addWidget(context_label)
    context_row.addWidget(context_filter, 1)
    detail_column.addLayout(context_row)
    axis_row = QHBoxLayout()
    axis_label = QLabel("Axis Mode")
    axis_label.setObjectName("section_header")
    axis_row.addWidget(axis_label)
    axis_row.addWidget(axis_filter, 1)
    detail_column.addLayout(axis_row)
    segment_row = QHBoxLayout()
    segment_label = QLabel("Segment")
    segment_label.setObjectName("section_header")
    segment_row.addWidget(segment_label)
    segment_row.addWidget(segment_filter, 1)
    detail_column.addLayout(segment_row)
    compare_row = QHBoxLayout()
    compare_label = QLabel("Compare Against")
    compare_label.setObjectName("section_header")
    compare_row.addWidget(compare_label)
    compare_row.addWidget(compare_filter, 1)
    detail_column.addLayout(compare_row)
    detail_column.addWidget(chart.widget)
    notes_header = QLabel("Session Notes")
    notes_header.setObjectName("section_header")
    detail_column.addWidget(notes_header)
    detail_column.addWidget(notes)
    markers_header = QLabel("Markers")
    markers_header.setObjectName("section_header")
    detail_column.addWidget(markers_header)
    detail_column.addWidget(markers_table)

    content_row = QHBoxLayout()
    content_row.addLayout(session_list_column, 2)
    content_row.addLayout(detail_column, 5)
    layout.addLayout(content_row)

    actions = QHBoxLayout()
    actions.addWidget(export_csv)
    actions.addWidget(export_json)
    actions.addWidget(export_analysis)
    actions.addWidget(export_segments)
    actions.addWidget(export_chart)
    layout.addLayout(actions)

    return _PanelRefs(
        panel=panel,
        refs={
            "active": active, "count": count, "summary": summary,
            "compare_summary": compare_summary,
            "database": database, "export_status": export_status,
            "recent": recent, "notes": notes, "markers_table": markers_table,
            "context_filter": context_filter, "context_label": context_label,
            "axis_filter": axis_filter, "axis_label": axis_label,
            "segment_filter": segment_filter, "segment_label": segment_label,
            "compare_filter": compare_filter, "compare_label": compare_label,
            "export_csv": export_csv, "export_json": export_json,
            "export_analysis": export_analysis, "export_segments": export_segments,
            "export_chart": export_chart, "chart": chart,
        },
    )


def _settings_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    database = QLabel()
    database.setWordWrap(True)
    diagnostics = QLabel()
    diagnostics.setWordWrap(True)
    export_dir_input = QLineEdit()
    export_dir_input.setToolTip("Set the default directory for exports")
    apply_button = QPushButton("Apply Export Directory")
    apply_button.setToolTip("Save the export directory setting")

    apply_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: runtime.presenter.set_export_directory(export_dir_input.text()))
    )

    theme_combo = QComboBox()
    theme_combo.addItem("Light", "light")
    theme_combo.addItem("Dark", "dark")
    theme_combo.addItem("Fluke", "fluke")
    theme_combo.setToolTip("Switch UI theme")

    def _on_theme_changed(index: int) -> None:
        import apps.desktop.theme as _theme
        theme_id = theme_combo.itemData(index)
        entry = _theme.THEMES.get(theme_id, _theme.THEMES["light"])
        _theme.active_theme = theme_id
        app_instance = QApplication.instance()
        if app_instance is not None:
            app_instance.setStyleSheet(entry["stylesheet"])
        # Update chart colors for all chart widgets stored in panel refs
        main = window
        for panel_attr in ("_live", "_session"):
            panel_refs = getattr(main, panel_attr, None)
            if panel_refs is None:
                continue
            chart = panel_refs.refs.get("chart")
            if chart is not None and hasattr(chart, "apply_theme"):
                chart.apply_theme(entry)
        # Update status bar label colors
        sb_color = entry.get("status_bar_text", "#6B7280")
        for sb_attr in ("_sb_connection", "_sb_session", "_sb_reading"):
            lbl = getattr(main, sb_attr, None)
            if lbl is not None:
                lbl.setStyleSheet(f"font-size: 11px; color: {sb_color};")

    theme_combo.currentIndexChanged.connect(_on_theme_changed)

    theme_form = QFormLayout()
    theme_form.addRow("Theme", theme_combo)

    for widget in (database, diagnostics, export_dir_input, apply_button):
        layout.addWidget(widget)
    layout.addLayout(theme_form)
    layout.addStretch()

    return _PanelRefs(
        panel=panel,
        refs={
            "database": database, "diagnostics": diagnostics,
            "export_dir_input": export_dir_input, "theme_combo": theme_combo,
        },
    )


def _workflow_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)

    status = QLabel()
    status.setWordWrap(True)
    title = QLabel()
    workflow_list = QListWidget()
    description = QLabel()
    description.setWordWrap(True)
    progress = QLabel()
    current_step = QLabel()
    instruction = QLabel()
    instruction.setWordWrap(True)
    requirement = QLabel()
    interaction_mode = QLabel()
    capture_state = QLabel()
    capture_hint = QLabel()
    capture_hint.setWordWrap(True)
    active_session = QLabel()
    latest_capture = QLabel()
    run_result = QLabel()
    selected_run = QLabel()
    selected_run.setWordWrap(True)
    note_input = QLineEdit()
    note_input.setPlaceholderText("Optional step note")
    note_input.setToolTip("Add an optional note when completing or skipping a step")
    report_view = QTextEdit()
    report_view.setReadOnly(True)
    report_view.setMinimumHeight(180)

    completed_steps = _make_table(["Title", "Status", "Detail"], min_height=100)
    recent_runs = _make_table(["Title", "Started", "Result", "Session"], min_height=100)

    start_button = QPushButton("Start Workflow")
    start_button.setObjectName("primary_button")
    start_button.setToolTip("Start the selected workflow")
    new_workflow_button = QPushButton("New Workflow")
    new_workflow_button.setToolTip("Create a new workflow definition from the desktop app")
    complete_button = QPushButton("Complete Step")
    complete_button.setToolTip("Complete the current workflow step and capture reading")
    continue_button = QPushButton("Continue")
    continue_button.setToolTip("Continue after accepting a captured reading")
    retake_button = QPushButton("Retake")
    retake_button.setToolTip("Discard the staged reading and capture the current step again")
    skip_button = QPushButton("Skip Step")
    skip_button.setToolTip("Skip the current workflow step")
    cancel_button = QPushButton("Cancel Workflow")
    cancel_button.setObjectName("danger_button")
    cancel_button.setToolTip("Cancel the running workflow")
    export_report_button = QPushButton("Export Workflow Report")
    export_report_button.setToolTip("Export the selected workflow run report as Markdown")

    def on_selection_changed() -> None:
        item = workflow_list.currentItem()
        runtime.presenter.select_workflow(None if item is None else item.data(0x0100))

    def on_recent_run_changed() -> None:
        runtime.presenter.select_workflow_run(_selected_table_id(recent_runs))

    workflow_list.itemSelectionChanged.connect(on_selection_changed)
    recent_runs.itemSelectionChanged.connect(on_recent_run_changed)
    start_button.clicked.connect(lambda: _safe_call(runtime, lambda: runtime.presenter.start_workflow()))
    new_workflow_button.clicked.connect(lambda: _open_workflow_builder(window, runtime))
    complete_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: _complete_workflow_step(runtime, note_input))
    )
    continue_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: _continue_workflow_capture(runtime, note_input))
    )
    retake_button.clicked.connect(lambda: _safe_call(runtime, runtime.presenter.retake_workflow_capture))
    skip_button.clicked.connect(lambda: _safe_call(runtime, lambda: _skip_workflow_step(runtime, note_input)))
    cancel_button.clicked.connect(
        lambda: _confirm_and_cancel_workflow(window, runtime)
    )
    export_report_button.clicked.connect(
        lambda: _export_and_notify(
            window,
            runtime,
            lambda: runtime.presenter.export_workflow_report(
                _workflow_report_export_path(runtime),
                run_id=_selected_workflow_run_id(runtime),
            ),
            "Workflow Report",
        )
    )

    left = QVBoxLayout()
    wf_header = QLabel("Available Workflows")
    wf_header.setObjectName("section_header")
    left.addWidget(wf_header)
    left.addWidget(workflow_list)
    left.addWidget(start_button)
    left.addWidget(new_workflow_button)

    actions = QHBoxLayout()
    actions.addWidget(complete_button)
    actions.addWidget(continue_button)
    actions.addWidget(retake_button)
    actions.addWidget(skip_button)
    actions.addWidget(cancel_button)

    right = QVBoxLayout()
    for widget in (
        status, title, description, progress, current_step,
        instruction, requirement, interaction_mode, capture_state, capture_hint,
        active_session, latest_capture, run_result, selected_run, note_input,
    ):
        right.addWidget(widget)
    steps_header = QLabel("Completed Steps")
    steps_header.setObjectName("section_header")
    right.addWidget(steps_header)
    right.addWidget(completed_steps)
    runs_header = QLabel("Recent Workflow Runs")
    runs_header.setObjectName("section_header")
    right.addWidget(runs_header)
    right.addWidget(recent_runs)
    report_header = QLabel("Workflow Report")
    report_header.setObjectName("section_header")
    right.addWidget(report_header)
    right.addWidget(report_view)
    right.addLayout(actions)
    right.addWidget(export_report_button)

    content = QHBoxLayout()
    content.addLayout(left, 2)
    content.addLayout(right, 5)
    layout.addLayout(content)

    return _PanelRefs(
        panel=panel,
        refs={
            "status": status, "title": title, "workflow_list": workflow_list,
            "description": description, "progress": progress,
            "current_step": current_step, "instruction": instruction,
            "requirement": requirement, "active_session": active_session,
            "latest_capture": latest_capture, "run_result": run_result,
            "selected_run": selected_run, "report_view": report_view,
            "note_input": note_input, "completed_steps": completed_steps,
            "recent_runs": recent_runs,
            "start_button": start_button, "new_workflow_button": new_workflow_button,
            "complete_button": complete_button,
            "continue_button": continue_button,
            "retake_button": retake_button,
            "skip_button": skip_button, "cancel_button": cancel_button,
            "export_report_button": export_report_button,
            "list_item_cls": QListWidgetItem,
            "interaction_mode": interaction_mode,
            "capture_state": capture_state,
            "capture_hint": capture_hint,
        },
    )


# ---------------------------------------------------------------------------
# Connection dot colors
# ---------------------------------------------------------------------------

_HEALTH_COLORS = {
    "connecting": "#3B82F6",
    "streaming": "#16A34A",
    "connected": "#D97706",
    "reconnecting": "#D97706",
    "stale": "#D97706",
    "disconnected": "#DC2626",
    "error": "#DC2626",
    "idle": "#9CA3AF",
}


def _update_connection_dot(dot_label, health: str) -> None:
    color = _HEALTH_COLORS.get(health, "#9CA3AF")
    dot_label.setStyleSheet(f"color: {color}; font-size: 11px;")


# ---------------------------------------------------------------------------
# Refresh functions
# ---------------------------------------------------------------------------

def _refresh_home(runtime, panel: _PanelRefs) -> None:
    home = runtime.presenter.home_view_model()
    panel.refs["title"].setText(home.title)
    panel.refs["subtitle"].setText(home.subtitle)
    panel.refs["connection"].setText(f"Connection: {home.connection_text}")
    _update_connection_dot(panel.refs["connection_dot"], home.connection_health)
    panel.refs["device"].setText(f"Device: {home.active_device_text}")
    panel.refs["session"].setText(f"Session: {home.active_session_text}")
    panel.refs["message"].setText(home.message_text)
    _sync_table_rows(
        panel.refs["recent_devices"],
        [(d.device_id, [d.label, d.support_text, d.last_seen_text]) for d in home.recent_devices],
    )
    is_busy = getattr(home, "is_busy", False)
    panel.refs["scan_button"].setEnabled(not is_busy and not home.is_connected)
    panel.refs["reconnect_button"].setEnabled(not is_busy and not home.is_connected)


def _refresh_discovery(runtime, panel: _PanelRefs) -> None:
    discovery = runtime.presenter.discovery_view_model()
    panel.refs["status"].setText(discovery.status_text)
    device_table = panel.refs["device_table"]
    _sync_table_rows(
        device_table,
        [(d.device_id, [d.label, d.model_name, d.rssi_text, d.support_text]) for d in discovery.devices],
    )
    if discovery.selected_device_id is not None:
        for i in range(device_table.rowCount()):
            item = device_table.item(i, 0)
            if item and item.data(0x0100) == discovery.selected_device_id:
                if device_table.currentRow() != i:
                    device_table.selectRow(i)
                break
    is_scanning = getattr(discovery, "is_scanning", False)
    is_connecting = getattr(discovery, "is_connecting", False)
    is_reconnecting = getattr(discovery, "is_reconnecting", False)
    panel.refs["scan_button"].setEnabled(not is_scanning and not is_connecting and not is_reconnecting)
    panel.refs["connect_button"].setEnabled(
        discovery.selected_device_id is not None and not is_scanning and not is_connecting and not is_reconnecting
    )


def _refresh_live(runtime, panel: _PanelRefs) -> None:
    runtime.presenter.check_reading_freshness()
    live = runtime.presenter.live_view_model()
    panel.refs["value"].setText(live.main_value)
    panel.refs["unit"].setText(live.unit_text)
    panel.refs["measurement"].setText(live.measurement_label)
    panel.refs["status"].setText(f"Status: {live.status_text}")
    panel.refs["connection"].setText(f"Connection: {live.connection_text}")
    _update_connection_dot(panel.refs["connection_dot"], live.connection_health)
    chart_notice = panel.refs["chart_notice"]
    chart_notice.setText(live.chart_notice_text)
    chart_notice.setVisible(bool(live.chart_notice_text))
    panel.refs["session"].setText(f"Session: {live.session_title or 'No active session'}")
    panel.refs["last_updated"].setText(f"Last Update: {live.last_updated_text}")
    panel.refs["summary"].setText(live.summary_text)
    panel.refs["marker_count"].setText(live.marker_count_text)
    panel.refs["alert_status"].setText(live.alert_status_text)
    chart_mode = panel.refs["chart_mode"]
    current_chart_index = chart_mode.findData(live.selected_chart_mode)
    if current_chart_index >= 0 and chart_mode.currentIndex() != current_chart_index:
        chart_mode.blockSignals(True)
        try:
            chart_mode.setCurrentIndex(current_chart_index)
        finally:
            chart_mode.blockSignals(False)
    panel.refs["start_button"].setEnabled(live.is_connected and not live.is_logging)
    panel.refs["stop_button"].setEnabled(live.is_logging)
    panel.refs["add_marker_button"].setEnabled(live.is_logging)
    panel.refs["marker_input"].setEnabled(live.is_logging)
    panel.refs["export_chart_button"].setEnabled(bool(live.chart_points))
    panel.refs["disconnect_button"].setEnabled(live.is_connected)
    alert_banner = panel.refs["alert_banner"]
    alert_banner.setText(live.alert_message)
    alert_banner.setVisible(live.alert_active)
    last_alert_event_id = panel.refs.get("last_alert_event_id", 0)
    if live.alert_active and live.alert_event_id > last_alert_event_id:
        QApplication.beep()
    panel.refs["last_alert_event_id"] = live.alert_event_id
    panel.refs["chart"].set_data(
        live.chart_points, live.marker_points,
        unit_text=live.unit_text,
        measurement_label=live.measurement_label,
        x_axis_mode=live.chart_x_mode,
        x_axis_title=live.chart_x_title,
    )
    title_input = panel.refs["title_input"]
    if live.session_title and not title_input.text():
        title_input.setText(live.session_title)


def _refresh_session(runtime, panel: _PanelRefs) -> None:
    session = runtime.presenter.session_view_model()
    panel.refs["active"].setText(f"Selected Session: {session.active_title_text}")
    panel.refs["count"].setText(session.reading_count_text)
    panel.refs["summary"].setText(session.selected_summary_text)
    panel.refs["compare_summary"].setText(session.compare_summary_text)
    panel.refs["compare_summary"].setVisible(bool(session.compare_summary_text))
    panel.refs["database"].setText(f"Database: {session.database_path_text}")
    panel.refs["export_status"].setText(session.export_status_text)

    _sync_table_rows(
        panel.refs["recent"],
        [(e.session_id, [e.title, e.started_at_text, e.ended_at_text]) for e in session.recent_sessions],
    )
    if session.selected_session_id is not None:
        recent = panel.refs["recent"]
        for i in range(recent.rowCount()):
            item = recent.item(i, 0)
            if item and item.data(0x0100) == session.selected_session_id:
                if recent.currentRow() != i:
                    recent.selectRow(i)
                break

    notes = panel.refs["notes"]
    if notes.toPlainText() != session.selected_session_notes:
        notes.setPlainText(session.selected_session_notes)

    markers_table = panel.refs["markers_table"]
    marker_rows = [(m.marker_id, [m.timestamp_text, m.label, m.note]) for m in session.selected_markers]
    if marker_rows:
        markers_table.clearSpans()
        _sync_table_rows(markers_table, marker_rows)
    else:
        markers_table.clearSpans()
        markers_table.clearContents()
        markers_table.setRowCount(1)
        placeholder_item = QTableWidgetItem("No markers recorded for this session.")
        placeholder_item.setFlags(Qt.ItemFlag.NoItemFlags)
        markers_table.setItem(0, 0, placeholder_item)
        markers_table.setSpan(0, 0, 1, markers_table.columnCount())
    _sync_combo_rows(
        panel.refs["context_filter"],
        [(None, "All Measurements")] + [(ctx.context_id, ctx.display_text) for ctx in session.available_contexts],
        session.selected_context_id,
    )
    _sync_combo_rows(
        panel.refs["axis_filter"],
        [("elapsed", "Elapsed Time"), ("utc", "UTC Timestamp"), ("by_segment", "By Segment")],
        session.selected_axis_mode,
    )
    _sync_combo_rows(
        panel.refs["segment_filter"],
        [(None, "All Segments")] + [(segment.segment_id, segment.display_text) for segment in session.available_segments],
        session.selected_segment_id,
    )
    _sync_combo_rows(
        panel.refs["compare_filter"],
        [(None, "No Comparison")] + [(item.session_id, item.display_text) for item in session.available_compare_sessions],
        session.compare_session_id,
    )
    show_context_filter = bool(session.available_contexts)
    show_segment_filter = session.selected_axis_mode == "by_segment" and bool(session.available_segments)
    show_compare_filter = bool(session.available_compare_sessions)
    panel.refs["context_filter"].setVisible(show_context_filter)
    panel.refs["context_label"].setVisible(show_context_filter)
    panel.refs["axis_filter"].setVisible(True)
    panel.refs["axis_label"].setVisible(True)
    panel.refs["segment_filter"].setVisible(show_segment_filter)
    panel.refs["segment_label"].setVisible(show_segment_filter)
    panel.refs["compare_filter"].setVisible(show_compare_filter)
    panel.refs["compare_label"].setVisible(show_compare_filter)

    panel.refs["export_csv"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_json"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_analysis"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_segments"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_chart"].setEnabled(bool(session.chart_points))
    panel.refs["chart"].set_data(
        session.chart_points, session.marker_points,
        unit_text=session.selected_unit_text,
        measurement_label=session.selected_context_label or "Session Replay",
        x_axis_mode=session.chart_x_mode,
        x_axis_title=session.chart_x_title,
        comparison_points=session.compare_chart_points,
        comparison_label=session.compare_session_label or "Comparison",
    )


def _refresh_settings(runtime, panel: _PanelRefs) -> None:
    settings = runtime.presenter.settings_view_model()
    panel.refs["database"].setText(f"Database: {settings.database_path_text}")
    panel.refs["diagnostics"].setText(settings.diagnostics_text)
    export_dir_input = panel.refs["export_dir_input"]
    if export_dir_input.text() != settings.export_directory_text:
        export_dir_input.setText(settings.export_directory_text)


def _refresh_workflow(runtime, panel: _PanelRefs) -> None:
    workflow = runtime.presenter.workflow_view_model()
    panel.refs["status"].setText(workflow.status_text)
    panel.refs["title"].setText(workflow.current_title_text)
    panel.refs["description"].setText(workflow.current_description_text)
    panel.refs["progress"].setText(f"Progress: {workflow.progress_text}")
    panel.refs["current_step"].setText(f"Current Step: {workflow.current_step_title}")
    panel.refs["instruction"].setText(workflow.current_instruction_text)
    panel.refs["requirement"].setText(workflow.current_requirement_text)
    panel.refs["interaction_mode"].setText(
        f"Step Mode: {workflow.current_interaction_mode_text}" if workflow.current_interaction_mode_text else ""
    )
    panel.refs["capture_state"].setText(
        f"Capture State: {workflow.capture_state_text}" if workflow.capture_state_text else ""
    )
    panel.refs["capture_hint"].setText(workflow.capture_hint_text)
    panel.refs["active_session"].setText(f"Session: {workflow.active_session_text}")
    panel.refs["latest_capture"].setText(workflow.latest_capture_text)
    panel.refs["run_result"].setText(f"Run Result: {workflow.run_result_text}")
    panel.refs["selected_run"].setText(workflow.selected_run_summary_text)

    workflow_list = panel.refs["workflow_list"]
    item_cls = panel.refs["list_item_cls"]
    _sync_list_rows(
        workflow_list, item_cls,
        [(item.workflow_id, f"{item.title} | {item.category} | {item.step_count_text}") for item in workflow.workflows],
    )
    if workflow.selected_workflow_id is not None:
        for index in range(workflow_list.count()):
            item = workflow_list.item(index)
            if item.data(0x0100) == workflow.selected_workflow_id:
                if workflow_list.currentRow() != index:
                    workflow_list.setCurrentRow(index)
                break

    _sync_table_rows(
        panel.refs["completed_steps"],
        [(s.step_id, [s.title, s.status_text, s.detail_text]) for s in workflow.completed_steps],
    )
    _sync_table_rows(
        panel.refs["recent_runs"],
        [(r.run_id, [r.title, r.started_at_text, r.result_text, r.session_id]) for r in workflow.recent_runs],
    )
    recent_runs = panel.refs["recent_runs"]
    matched_run = False
    if workflow.selected_run_id is not None:
        for i in range(recent_runs.rowCount()):
            item = recent_runs.item(i, 0)
            if item and item.data(0x0100) == workflow.selected_run_id:
                if recent_runs.currentRow() != i:
                    recent_runs.selectRow(i)
                matched_run = True
                break
    if not matched_run and recent_runs.currentRow() != -1:
        recent_runs.clearSelection()

    report_view = panel.refs["report_view"]
    if report_view.toPlainText() != workflow.report_text:
        report_view.setPlainText(workflow.report_text)

    panel.refs["start_button"].setEnabled(workflow.selected_workflow_id is not None and not workflow.is_running)
    panel.refs["complete_button"].setText(workflow.primary_action_text)
    panel.refs["complete_button"].setEnabled(workflow.is_running)
    panel.refs["continue_button"].setEnabled(workflow.can_continue_capture)
    panel.refs["retake_button"].setEnabled(workflow.can_retake_capture)
    panel.refs["skip_button"].setEnabled(workflow.is_running)
    panel.refs["cancel_button"].setEnabled(workflow.is_running)
    panel.refs["note_input"].setEnabled(workflow.is_running)
    panel.refs["export_report_button"].setEnabled(workflow.selected_run_id is not None)


# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------

def _submit(runtime, coro) -> None:
    future = runtime.submit(coro)
    future.add_done_callback(lambda fut: _handle_future(runtime, fut))


def _safe_call(runtime, func) -> None:
    try:
        func()
    except Exception as exc:
        runtime.presenter.report_error(str(exc))


def _handle_future(runtime, future) -> None:
    exc = future.exception()
    if exc is not None:
        runtime.presenter.report_error(str(exc))


def _text_or_none(text: str) -> str | None:
    stripped = text.strip()
    return stripped or None


def _add_live_marker(runtime, marker_input) -> None:
    note = _text_or_none(marker_input.text())
    if note is None:
        raise RuntimeError("Enter a marker note before adding a marker.")
    runtime.presenter.add_marker(note)
    marker_input.clear()


def _toggle_logging(runtime, live_panel: _PanelRefs) -> None:
    """Ctrl+L handler: toggle logging on/off."""
    live = runtime.presenter.live_view_model()
    if live.is_logging:
        _safe_call(runtime, runtime.presenter.stop_logging)
    else:
        title_input = live_panel.refs.get("title_input")
        title = _text_or_none(title_input.text()) if title_input else None
        _safe_call(runtime, lambda: runtime.presenter.start_logging(title=title))


def _confirm_and_disconnect(window: QWidget, runtime) -> None:
    if _confirm(window, "Disconnect", "Disconnect from device? Any active logging will stop."):
        _submit(runtime, runtime.presenter.disconnect_device())


def _confirm_and_cancel_workflow(window: QWidget, runtime) -> None:
    if _confirm(window, "Cancel Workflow", "Cancel the running workflow?"):
        _safe_call(runtime, runtime.presenter.cancel_workflow)


def _open_workflow_builder(window: QWidget, runtime) -> None:
    dialog = _WorkflowBuilderDialog(window)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    try:
        definition = dialog.workflow_definition()
        exported = runtime.presenter.create_workflow(definition)
        _info(window, "Workflow Created", f"Workflow saved to:\n{exported}")
    except Exception as exc:
        runtime.presenter.report_error(str(exc))
        QMessageBox.warning(window, "Workflow Save Failed", str(exc))


def _export_chart_with_dialog(window: QWidget, runtime, chart, path: Path) -> None:
    try:
        exported = chart.export_png(path)
        runtime.presenter.set_export_status(f"Chart image exported to {exported}")
        _info(window, "Export Complete", f"Chart saved to:\n{exported}")
    except Exception as exc:
        runtime.presenter.report_error(str(exc))


def _export_and_notify(window: QWidget, runtime, func, format_label: str) -> None:
    try:
        exported = func()
        _info(window, "Export Complete", f"{format_label} export saved to:\n{exported}")
    except Exception as exc:
        runtime.presenter.report_error(str(exc))


def _selected_session_id(runtime) -> str | None:
    return runtime.presenter.session_view_model().selected_session_id


def _selected_workflow_run_id(runtime) -> str | None:
    return runtime.presenter.workflow_view_model().selected_run_id


def _export_directory(runtime) -> Path:
    configured = runtime.presenter.settings_view_model().export_directory_text.strip()
    return Path(configured or "exports")


def _session_export_path(runtime, extension: str) -> Path:
    session_id = _selected_session_id(runtime) or "desktop-session"
    if extension.startswith("."):
        suffix = extension
    elif "." in extension:
        suffix = f"-{extension}"
    else:
        suffix = f".{extension}"
    return _export_directory(runtime) / f"session-{session_id}{suffix}"


def _session_chart_export_path(runtime) -> Path:
    session_id = _selected_session_id(runtime) or "desktop-session"
    return _export_directory(runtime) / f"session-{session_id}-chart.png"


def _live_chart_export_path(runtime) -> Path:
    return _export_directory(runtime) / "live-chart.png"


def _workflow_report_export_path(runtime) -> Path:
    run_id = _selected_workflow_run_id(runtime) or "workflow-run"
    return _export_directory(runtime) / f"workflow-run-{run_id}.md"


def _complete_workflow_step(runtime, note_input) -> None:
    note = _text_or_none(note_input.text())
    runtime.presenter.complete_workflow_step(note=note)
    note_input.clear()


def _continue_workflow_capture(runtime, note_input) -> None:
    note = _text_or_none(note_input.text())
    runtime.presenter.continue_workflow_capture(note=note)
    note_input.clear()


def _skip_workflow_step(runtime, note_input) -> None:
    note = _text_or_none(note_input.text())
    runtime.presenter.skip_workflow_step(note=note)
    note_input.clear()


def _workflow_primary_shortcut(window: QWidget, runtime) -> None:
    if not _workflow_shortcut_allowed(window):
        return
    _safe_call(runtime, lambda: _complete_workflow_step(runtime, window._workflow.refs["note_input"]))  # type: ignore[attr-defined]


def _workflow_continue_shortcut(window: QWidget, runtime) -> None:
    if not _workflow_shortcut_allowed(window):
        return
    workflow = runtime.presenter.workflow_view_model()
    if workflow.can_continue_capture:
        _safe_call(runtime, lambda: _continue_workflow_capture(runtime, window._workflow.refs["note_input"]))  # type: ignore[attr-defined]


def _workflow_retake_shortcut(window: QWidget, runtime) -> None:
    if not _workflow_shortcut_allowed(window):
        return
    workflow = runtime.presenter.workflow_view_model()
    if workflow.can_retake_capture:
        _safe_call(runtime, runtime.presenter.retake_workflow_capture)


def _workflow_cancel_shortcut(window: QWidget, runtime) -> None:
    if not _workflow_shortcut_allowed(window):
        return
    workflow = runtime.presenter.workflow_view_model()
    if workflow.is_running:
        _safe_call(runtime, runtime.presenter.cancel_workflow)


def _workflow_shortcut_allowed(window: QWidget) -> bool:
    tabs = getattr(window, "_tabs", None)
    if tabs is None or tabs.currentIndex() != 4:  # type: ignore[attr-defined]
        return False
    focused = QApplication.focusWidget()
    return not isinstance(focused, (QLineEdit, QTextEdit))
