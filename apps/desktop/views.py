from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from apps.desktop._qt import (
    QAbstractItemView,
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
    QShortcut,
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


@dataclass(slots=True)
class _PanelRefs:
    panel: object
    refs: dict[str, object]


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


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

def create_main_window(runtime) -> QWidget:

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Fluke Community Desktop")
            self.setMinimumSize(800, 500)
            self.resize(1100, 720)

            root = QWidget()
            outer = QVBoxLayout(root)

            header = QHBoxLayout()
            title = QLabel("Fluke Community Desktop")
            title.setObjectName("section_header")
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            subtitle = QLabel("Connect, view, and log readings from supported meters.")
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
                lambda: _safe_call(runtime, lambda: runtime.presenter.export_session_csv(
                    _session_export_path(runtime, "csv"),
                    session_id=_selected_session_id(runtime),
                ))
            )

            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(250)
            self._refresh_timer.timeout.connect(self._refresh)
            self._refresh_timer.start()
            self._refresh()

        def closeEvent(self, event) -> None:  # type: ignore[override]
            super().closeEvent(event)

        def _refresh(self) -> None:
            _refresh_home(runtime, self._home)
            _refresh_discovery(runtime, self._discovery)
            _refresh_live(runtime, self._live)
            _refresh_session(runtime, self._session)
            _refresh_workflow(runtime, self._workflow)
            _refresh_settings(runtime, self._settings)

    return MainWindow()


# ---------------------------------------------------------------------------
# Panels
# ---------------------------------------------------------------------------

def _home_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    title = QLabel()
    subtitle = QLabel()
    connection = QLabel()
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

    for widget in (title, subtitle, connection, device, session, message, recent_devices):
        layout.addWidget(widget)
    btn_row = QHBoxLayout()
    btn_row.addWidget(scan_button)
    btn_row.addWidget(reconnect_button)
    layout.addLayout(btn_row)
    layout.addStretch()

    return _PanelRefs(
        panel=panel,
        refs={
            "title": title, "subtitle": subtitle, "connection": connection,
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
    connection = QLabel()
    last_updated = QLabel()
    session = QLabel()
    summary = QLabel()
    marker_count = QLabel()
    chart = build_reading_chart(
        title="Live Reading",
        empty_text="Connect to a supported meter to start plotting live data.",
    )
    title_input = QLineEdit()
    notes_input = QTextEdit()
    notes_input.setFixedHeight(80)
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

    action_row = QHBoxLayout()
    action_row.addWidget(start_button)
    action_row.addWidget(stop_button)
    action_row.addWidget(export_chart_button)
    action_row.addWidget(disconnect_button)

    marker_row = QHBoxLayout()
    marker_row.addWidget(marker_input, 1)
    marker_row.addWidget(add_marker_button)

    for widget in (value, unit, measurement, status, connection, session, last_updated, summary, marker_count):
        layout.addWidget(widget)
    layout.addWidget(chart.widget)
    layout.addLayout(form)
    layout.addLayout(marker_row)
    layout.addLayout(action_row)

    return _PanelRefs(
        panel=panel,
        refs={
            "value": value, "unit": unit, "measurement": measurement,
            "status": status, "connection": connection, "session": session,
            "last_updated": last_updated, "summary": summary,
            "marker_count": marker_count, "title_input": title_input,
            "marker_input": marker_input,
            "start_button": start_button, "stop_button": stop_button,
            "add_marker_button": add_marker_button,
            "export_chart_button": export_chart_button,
            "chart": chart,
        },
    )


def _session_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    active = QLabel()
    count = QLabel()
    summary = QLabel()
    database = QLabel()
    export_status = QLabel()

    recent = _make_table(["Title", "Started", "Ended"], min_height=150)
    markers_table = _make_table(["Time", "Label", "Note"], min_height=100)

    notes = QTextEdit()
    notes.setReadOnly(True)
    notes.setFixedHeight(90)
    chart = build_reading_chart(
        title="Session Replay",
        empty_text="Select a recorded session to inspect its replay chart and markers.",
    )
    export_csv = QPushButton("Export Session CSV")
    export_csv.setToolTip("Export the selected session as CSV (Ctrl+E)")
    export_json = QPushButton("Export Session JSON")
    export_json.setToolTip("Export the selected session as JSON")
    export_chart = QPushButton("Export Session Chart")
    export_chart.setToolTip("Save the session chart as a PNG image")

    def on_selection_changed() -> None:
        selected_id = _selected_table_id(recent)
        if selected_id is None:
            return
        _safe_call(runtime, lambda: runtime.presenter.select_session(selected_id))

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
    recent.itemSelectionChanged.connect(on_selection_changed)

    session_list_column = QVBoxLayout()
    header = QLabel("Recent Sessions")
    header.setObjectName("section_header")
    session_list_column.addWidget(header)
    session_list_column.addWidget(recent)

    detail_column = QVBoxLayout()
    for widget in (active, count, summary, database, export_status, chart.widget):
        detail_column.addWidget(widget)
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
    actions.addWidget(export_chart)
    layout.addLayout(actions)

    return _PanelRefs(
        panel=panel,
        refs={
            "active": active, "count": count, "summary": summary,
            "database": database, "export_status": export_status,
            "recent": recent, "notes": notes, "markers_table": markers_table,
            "export_csv": export_csv, "export_json": export_json,
            "export_chart": export_chart, "chart": chart,
        },
    )


def _settings_panel(window: QWidget, runtime) -> _PanelRefs:
    panel = QWidget()
    layout = QVBoxLayout(panel)
    database = QLabel()
    diagnostics = QLabel()
    diagnostics.setWordWrap(True)
    export_dir_input = QLineEdit()
    export_dir_input.setToolTip("Set the default directory for exports")
    apply_button = QPushButton("Apply Export Directory")
    apply_button.setToolTip("Save the export directory setting")

    apply_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: runtime.presenter.set_export_directory(export_dir_input.text()))
    )

    for widget in (database, diagnostics, export_dir_input, apply_button):
        layout.addWidget(widget)
    layout.addStretch()

    return _PanelRefs(
        panel=panel,
        refs={"database": database, "diagnostics": diagnostics, "export_dir_input": export_dir_input},
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
    active_session = QLabel()
    latest_capture = QLabel()
    run_result = QLabel()
    note_input = QLineEdit()
    note_input.setPlaceholderText("Optional step note")
    note_input.setToolTip("Add an optional note when completing or skipping a step")

    completed_steps = _make_table(["Title", "Status", "Detail"], min_height=100)
    recent_runs = _make_table(["Title", "Started", "Result", "Session"], min_height=100)

    start_button = QPushButton("Start Workflow")
    start_button.setObjectName("primary_button")
    start_button.setToolTip("Start the selected workflow")
    complete_button = QPushButton("Complete Step")
    complete_button.setToolTip("Complete the current workflow step and capture reading")
    skip_button = QPushButton("Skip Step")
    skip_button.setToolTip("Skip the current workflow step")
    cancel_button = QPushButton("Cancel Workflow")
    cancel_button.setObjectName("danger_button")
    cancel_button.setToolTip("Cancel the running workflow")

    def on_selection_changed() -> None:
        item = workflow_list.currentItem()
        runtime.presenter.select_workflow(None if item is None else item.data(0x0100))

    workflow_list.itemSelectionChanged.connect(on_selection_changed)
    start_button.clicked.connect(lambda: _safe_call(runtime, lambda: runtime.presenter.start_workflow()))
    complete_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: _complete_workflow_step(runtime, note_input))
    )
    skip_button.clicked.connect(lambda: _safe_call(runtime, lambda: _skip_workflow_step(runtime, note_input)))
    cancel_button.clicked.connect(
        lambda: _confirm_and_cancel_workflow(window, runtime)
    )

    left = QVBoxLayout()
    wf_header = QLabel("Available Workflows")
    wf_header.setObjectName("section_header")
    left.addWidget(wf_header)
    left.addWidget(workflow_list)
    left.addWidget(start_button)

    actions = QHBoxLayout()
    actions.addWidget(complete_button)
    actions.addWidget(skip_button)
    actions.addWidget(cancel_button)

    right = QVBoxLayout()
    for widget in (
        status, title, description, progress, current_step,
        instruction, requirement, active_session, latest_capture, run_result, note_input,
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
    right.addLayout(actions)

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
            "note_input": note_input, "completed_steps": completed_steps,
            "recent_runs": recent_runs,
            "start_button": start_button, "complete_button": complete_button,
            "skip_button": skip_button, "cancel_button": cancel_button,
            "list_item_cls": QListWidgetItem,
        },
    )


# ---------------------------------------------------------------------------
# Refresh functions
# ---------------------------------------------------------------------------

def _refresh_home(runtime, panel: _PanelRefs) -> None:
    home = runtime.presenter.home_view_model()
    panel.refs["title"].setText(home.title)
    panel.refs["subtitle"].setText(home.subtitle)
    panel.refs["connection"].setText(f"Connection: {home.connection_text}")
    panel.refs["device"].setText(f"Device: {home.active_device_text}")
    panel.refs["session"].setText(f"Session: {home.active_session_text}")
    panel.refs["message"].setText(home.message_text)
    _sync_table_rows(
        panel.refs["recent_devices"],
        [(d.device_id, [d.label, d.support_text, d.last_seen_text]) for d in home.recent_devices],
    )
    is_busy = getattr(home, "is_busy", False)
    panel.refs["scan_button"].setEnabled(not is_busy)
    panel.refs["reconnect_button"].setEnabled(not is_busy)


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
    panel.refs["scan_button"].setEnabled(not is_scanning and not is_connecting)
    panel.refs["connect_button"].setEnabled(
        discovery.selected_device_id is not None and not is_scanning and not is_connecting
    )


def _refresh_live(runtime, panel: _PanelRefs) -> None:
    live = runtime.presenter.live_view_model()
    panel.refs["value"].setText(live.main_value)
    panel.refs["unit"].setText(live.unit_text)
    panel.refs["measurement"].setText(live.measurement_label)
    panel.refs["status"].setText(f"Status: {live.status_text}")
    panel.refs["connection"].setText(f"Connection: {live.connection_text}")
    panel.refs["session"].setText(f"Session: {live.session_title or 'No active session'}")
    panel.refs["last_updated"].setText(f"Last Update: {live.last_updated_text}")
    panel.refs["summary"].setText(live.summary_text)
    panel.refs["marker_count"].setText(live.marker_count_text)
    panel.refs["start_button"].setEnabled(not live.is_logging)
    panel.refs["stop_button"].setEnabled(live.is_logging)
    panel.refs["add_marker_button"].setEnabled(live.is_logging)
    panel.refs["marker_input"].setEnabled(live.is_logging)
    panel.refs["export_chart_button"].setEnabled(bool(live.chart_points))
    panel.refs["chart"].set_data(
        live.chart_points, live.marker_points,
        unit_text=live.unit_text, measurement_label=live.measurement_label,
    )
    title_input = panel.refs["title_input"]
    if live.session_title and not title_input.text():
        title_input.setText(live.session_title)


def _refresh_session(runtime, panel: _PanelRefs) -> None:
    session = runtime.presenter.session_view_model()
    panel.refs["active"].setText(f"Selected Session: {session.active_title_text}")
    panel.refs["count"].setText(session.reading_count_text)
    panel.refs["summary"].setText(session.selected_summary_text)
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

    _sync_table_rows(
        panel.refs["markers_table"],
        [(m.marker_id, [m.timestamp_text, m.label, m.note]) for m in session.selected_markers],
    )

    panel.refs["export_csv"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_json"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_chart"].setEnabled(bool(session.chart_points))
    panel.refs["chart"].set_data(
        session.chart_points, session.marker_points,
        unit_text=session.selected_unit_text, measurement_label="Session Replay",
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
    panel.refs["active_session"].setText(f"Session: {workflow.active_session_text}")
    panel.refs["latest_capture"].setText(workflow.latest_capture_text)
    panel.refs["run_result"].setText(f"Run Result: {workflow.run_result_text}")

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

    panel.refs["start_button"].setEnabled(workflow.selected_workflow_id is not None and not workflow.is_running)
    panel.refs["complete_button"].setEnabled(workflow.is_running)
    panel.refs["skip_button"].setEnabled(workflow.is_running)
    panel.refs["cancel_button"].setEnabled(workflow.is_running)
    panel.refs["note_input"].setEnabled(workflow.is_running)


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
    if _confirm(window, "Disconnect", "Disconnect from device? Any active logging session will be stopped."):
        _submit(runtime, runtime.presenter.disconnect_device())


def _confirm_and_cancel_workflow(window: QWidget, runtime) -> None:
    if _confirm(window, "Cancel Workflow", "Cancel the running workflow?"):
        _safe_call(runtime, runtime.presenter.cancel_workflow)


def _export_chart_with_dialog(window: QWidget, runtime, chart, path: Path) -> None:
    try:
        exported = chart.export_png(path)
        runtime.presenter.set_export_status(f"Chart image exported to {exported}")
        _info(window, "Export Complete", f"Chart saved to:\n{exported}")
    except Exception as exc:
        runtime.presenter.report_error(str(exc))


def _export_and_notify(window: QWidget, runtime, func, format_label: str) -> None:
    try:
        func()
        _info(window, "Export Complete", f"{format_label} export saved successfully.")
    except Exception as exc:
        runtime.presenter.report_error(str(exc))


def _selected_session_id(runtime) -> str | None:
    return runtime.presenter.session_view_model().selected_session_id


def _export_directory(runtime) -> Path:
    configured = runtime.presenter.settings_view_model().export_directory_text.strip()
    return Path(configured or "exports")


def _session_export_path(runtime, extension: str) -> Path:
    session_id = _selected_session_id(runtime) or "desktop-session"
    return _export_directory(runtime) / f"session-{session_id}.{extension}"


def _session_chart_export_path(runtime) -> Path:
    session_id = _selected_session_id(runtime) or "desktop-session"
    return _export_directory(runtime) / f"session-{session_id}-chart.png"


def _live_chart_export_path(runtime) -> Path:
    return _export_directory(runtime) / "live-chart.png"


def _complete_workflow_step(runtime, note_input) -> None:
    note = _text_or_none(note_input.text())
    runtime.presenter.complete_workflow_step(note=note)
    note_input.clear()


def _skip_workflow_step(runtime, note_input) -> None:
    note = _text_or_none(note_input.text())
    runtime.presenter.skip_workflow_step(note=note)
    note_input.clear()
