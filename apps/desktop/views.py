from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from apps.desktop.widgets import build_reading_chart

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def _require_qt():
    try:
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import (
            QApplication,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QListWidget,
            QListWidgetItem,
            QMainWindow,
            QPushButton,
            QTabWidget,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySide6 is required to launch the desktop UI.") from exc

    return {
        "Qt": Qt,
        "QTimer": QTimer,
        "QApplication": QApplication,
        "QFormLayout": QFormLayout,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QLineEdit": QLineEdit,
        "QListWidget": QListWidget,
        "QListWidgetItem": QListWidgetItem,
        "QMainWindow": QMainWindow,
        "QPushButton": QPushButton,
        "QTabWidget": QTabWidget,
        "QTextEdit": QTextEdit,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }


@dataclass(slots=True)
class _PanelRefs:
    panel: object
    refs: dict[str, object]


def create_main_window(runtime) -> "QWidget":
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QMainWindow = qt["QMainWindow"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QTabWidget = qt["QTabWidget"]
    QTimer = qt["QTimer"]
    Qt = qt["Qt"]

    class MainWindow(QMainWindow):
        def __init__(self) -> None:
            super().__init__()
            self.setWindowTitle("Fluke Community Desktop")
            self.resize(1100, 720)

            root = QWidget()
            outer = QVBoxLayout(root)

            header = QHBoxLayout()
            title = QLabel("Fluke Community Desktop")
            title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            subtitle = QLabel("Connect, view, and log readings from supported meters.")
            header.addWidget(title, 2)
            header.addWidget(subtitle, 3)
            outer.addLayout(header)

            tabs = QTabWidget()
            self._home = _home_panel(runtime, qt)
            self._discovery = _discovery_panel(runtime, qt)
            self._live = _live_panel(runtime, qt)
            self._session = _session_panel(runtime, qt)
            self._settings = _settings_panel(runtime, qt)
            tabs.addTab(self._home.panel, "Home")
            tabs.addTab(self._discovery.panel, "Device Discovery")
            tabs.addTab(self._live.panel, "Live Reading")
            tabs.addTab(self._session.panel, "Session")
            tabs.addTab(self._settings.panel, "Settings")
            outer.addWidget(tabs)
            self.setCentralWidget(root)

            self._refresh_timer = QTimer(self)
            self._refresh_timer.setInterval(250)
            self._refresh_timer.timeout.connect(self._refresh)
            self._refresh_timer.start()
            self._refresh()

        def closeEvent(self, event) -> None:  # type: ignore[override]
            runtime.close()
            super().closeEvent(event)

        def _refresh(self) -> None:
            _refresh_home(runtime, self._home)
            _refresh_discovery(runtime, self._discovery)
            _refresh_live(runtime, self._live)
            _refresh_session(runtime, self._session)
            _refresh_settings(runtime, self._settings)

    return MainWindow()


def _home_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QLabel = qt["QLabel"]
    QListWidget = qt["QListWidget"]
    QPushButton = qt["QPushButton"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]

    panel = QWidget()
    layout = QVBoxLayout(panel)
    title = QLabel()
    subtitle = QLabel()
    connection = QLabel()
    device = QLabel()
    session = QLabel()
    message = QLabel()
    recent_devices = QListWidget()
    scan_button = QPushButton("Find Meters")
    reconnect_button = QPushButton("Reconnect Last Device")
    scan_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.scan_devices(timeout_s=5.0)))
    reconnect_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.reconnect_last_device()))

    for widget in (title, subtitle, connection, device, session, message, recent_devices, scan_button, reconnect_button):
        layout.addWidget(widget)

    return _PanelRefs(
        panel=panel,
        refs={
            "title": title,
            "subtitle": subtitle,
            "connection": connection,
            "device": device,
            "session": session,
            "message": message,
            "recent_devices": recent_devices,
            "list_item_cls": qt["QListWidgetItem"],
        },
    )


def _discovery_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QLabel = qt["QLabel"]
    QListWidget = qt["QListWidget"]
    QListWidgetItem = qt["QListWidgetItem"]
    QPushButton = qt["QPushButton"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]

    panel = QWidget()
    layout = QVBoxLayout(panel)
    description = QLabel("Scan for nearby meters and connect to a supported profile.")
    status = QLabel()
    device_list = QListWidget()
    scan_button = QPushButton("Scan")
    connect_button = QPushButton("Connect")
    connect_button.setEnabled(False)

    def on_selection_changed() -> None:
        item = device_list.currentItem()
        selected_id = None if item is None else item.data(0x0100)
        runtime.presenter.select_device(selected_id)
        connect_button.setEnabled(selected_id is not None)

    def on_connect() -> None:
        item = device_list.currentItem()
        if item is None:
            return
        _submit(runtime, runtime.presenter.connect_device(item.data(0x0100)))

    device_list.itemSelectionChanged.connect(on_selection_changed)
    scan_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.scan_devices(timeout_s=5.0)))
    connect_button.clicked.connect(on_connect)

    for widget in (description, status, device_list, scan_button, connect_button):
        layout.addWidget(widget)

    return _PanelRefs(
        panel=panel,
        refs={
            "status": status,
            "device_list": device_list,
            "list_item_cls": QListWidgetItem,
            "connect_button": connect_button,
        },
    )


def _live_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QTextEdit = qt["QTextEdit"]
    QPushButton = qt["QPushButton"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]
    QFormLayout = qt["QFormLayout"]

    panel = QWidget()
    layout = QVBoxLayout(panel)
    value = QLabel()
    value.setStyleSheet("font-size: 42px; font-weight: 700;")
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
    stop_button = QPushButton("Stop Logging")
    add_marker_button = QPushButton("Add Marker")
    export_chart_button = QPushButton("Export Live Chart")
    disconnect_button = QPushButton("Disconnect")

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
        lambda: _safe_call(
            runtime,
            lambda: _add_live_marker(runtime, marker_input),
        )
    )
    export_chart_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: _export_chart(runtime, chart, _live_chart_export_path(runtime)))
    )
    disconnect_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.disconnect_device()))

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
            "value": value,
            "unit": unit,
            "measurement": measurement,
            "status": status,
            "connection": connection,
            "session": session,
            "last_updated": last_updated,
            "summary": summary,
            "marker_count": marker_count,
            "title_input": title_input,
            "marker_input": marker_input,
            "start_button": start_button,
            "stop_button": stop_button,
            "add_marker_button": add_marker_button,
            "export_chart_button": export_chart_button,
            "chart": chart,
        },
    )


def _session_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QListWidget = qt["QListWidget"]
    QListWidgetItem = qt["QListWidgetItem"]
    QPushButton = qt["QPushButton"]
    QTextEdit = qt["QTextEdit"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]

    panel = QWidget()
    layout = QVBoxLayout(panel)
    active = QLabel()
    count = QLabel()
    summary = QLabel()
    database = QLabel()
    export_status = QLabel()
    recent = QListWidget()
    notes = QTextEdit()
    notes.setReadOnly(True)
    notes.setFixedHeight(90)
    markers = QListWidget()
    chart = build_reading_chart(
        title="Session Replay",
        empty_text="Select a recorded session to inspect its replay chart and markers.",
    )
    export_csv = QPushButton("Export Session CSV")
    export_json = QPushButton("Export Session JSON")
    export_chart = QPushButton("Export Session Chart")

    def on_selection_changed() -> None:
        item = recent.currentItem()
        if item is None:
            return
        _safe_call(runtime, lambda: runtime.presenter.select_session(item.data(0x0100)))

    export_csv.clicked.connect(
        lambda: _safe_call(
            runtime,
            lambda: runtime.presenter.export_session_csv(
                _session_export_path(runtime, "csv"),
                session_id=_selected_session_id(runtime),
            ),
        )
    )
    export_json.clicked.connect(
        lambda: _safe_call(
            runtime,
            lambda: runtime.presenter.export_session_json(
                _session_export_path(runtime, "json"),
                session_id=_selected_session_id(runtime),
            ),
        )
    )
    export_chart.clicked.connect(
        lambda: _safe_call(runtime, lambda: _export_chart(runtime, chart, _session_chart_export_path(runtime)))
    )
    recent.itemSelectionChanged.connect(on_selection_changed)

    session_list_column = QVBoxLayout()
    session_list_column.addWidget(QLabel("Recent Sessions"))
    session_list_column.addWidget(recent)

    detail_column = QVBoxLayout()
    for widget in (
        active,
        count,
        summary,
        database,
        export_status,
        chart.widget,
        QLabel("Session Notes"),
        notes,
        QLabel("Markers"),
        markers,
    ):
        detail_column.addWidget(widget)

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
            "active": active,
            "count": count,
            "summary": summary,
            "database": database,
            "export_status": export_status,
            "recent": recent,
            "notes": notes,
            "markers": markers,
            "list_item_cls": QListWidgetItem,
            "export_csv": export_csv,
            "export_json": export_json,
            "export_chart": export_chart,
            "chart": chart,
        },
    )


def _settings_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QLabel = qt["QLabel"]
    QLineEdit = qt["QLineEdit"]
    QPushButton = qt["QPushButton"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]

    panel = QWidget()
    layout = QVBoxLayout(panel)
    database = QLabel()
    diagnostics = QLabel()
    export_dir_input = QLineEdit()
    apply_button = QPushButton("Apply Export Directory")

    apply_button.clicked.connect(
        lambda: _safe_call(runtime, lambda: runtime.presenter.set_export_directory(export_dir_input.text()))
    )

    for widget in (database, diagnostics, export_dir_input, apply_button):
        layout.addWidget(widget)

    return _PanelRefs(
        panel=panel,
        refs={
            "database": database,
            "diagnostics": diagnostics,
            "export_dir_input": export_dir_input,
        },
    )


def _refresh_home(runtime, panel: _PanelRefs) -> None:
    home = runtime.presenter.home_view_model()
    panel.refs["title"].setText(home.title)
    panel.refs["subtitle"].setText(home.subtitle)
    panel.refs["connection"].setText(f"Connection: {home.connection_text}")
    panel.refs["device"].setText(f"Device: {home.active_device_text}")
    panel.refs["session"].setText(f"Session: {home.active_session_text}")
    panel.refs["message"].setText(home.message_text)
    recent = panel.refs["recent_devices"]
    item_cls = panel.refs["list_item_cls"]
    current = [recent.item(index).data(0x0100) for index in range(recent.count())]
    desired = [device.device_id for device in home.recent_devices]
    if current != desired:
        recent.clear()
        for device in home.recent_devices:
            item = item_cls(f"{device.label} | support={device.support_text} | last_seen={device.last_seen_text}")
            item.setData(0x0100, device.device_id)
            recent.addItem(item)


def _refresh_discovery(runtime, panel: _PanelRefs) -> None:
    discovery = runtime.presenter.discovery_view_model()
    panel.refs["status"].setText(discovery.status_text)
    list_widget = panel.refs["device_list"]
    item_cls = panel.refs["list_item_cls"]
    current_ids = [list_widget.item(index).data(0x0100) for index in range(list_widget.count())]
    desired_ids = [device.device_id for device in discovery.devices]
    if current_ids != desired_ids:
        list_widget.clear()
        for device in discovery.devices:
            label = f"{device.label} | {device.model_name} | {device.rssi_text} | {device.support_text}"
            item = item_cls(label)
            item.setData(0x0100, device.device_id)
            list_widget.addItem(item)
    if discovery.selected_device_id is not None:
        for index in range(list_widget.count()):
            item = list_widget.item(index)
            if item.data(0x0100) == discovery.selected_device_id:
                if list_widget.currentRow() != index:
                    list_widget.setCurrentRow(index)
                break
    panel.refs["connect_button"].setEnabled(discovery.selected_device_id is not None)


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
        live.chart_points,
        live.marker_points,
        unit_text=live.unit_text,
        measurement_label=live.measurement_label,
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
    recent = panel.refs["recent"]
    item_cls = panel.refs["list_item_cls"]
    current_ids = [recent.item(index).data(0x0100) for index in range(recent.count())]
    desired_ids = [entry.session_id for entry in session.recent_sessions]
    if current_ids != desired_ids:
        recent.clear()
        for entry in session.recent_sessions:
            label = f"{entry.title} | {entry.started_at_text} | ended={entry.ended_at_text}"
            item = item_cls(label)
            item.setData(0x0100, entry.session_id)
            recent.addItem(item)
    if session.selected_session_id is not None:
        for index in range(recent.count()):
            item = recent.item(index)
            if item.data(0x0100) == session.selected_session_id:
                if recent.currentRow() != index:
                    recent.setCurrentRow(index)
                break
    notes = panel.refs["notes"]
    if notes.toPlainText() != session.selected_session_notes:
        notes.setPlainText(session.selected_session_notes)
    markers = panel.refs["markers"]
    current_marker_ids = [markers.item(index).data(0x0100) for index in range(markers.count())]
    desired_marker_ids = [marker.marker_id for marker in session.selected_markers]
    if current_marker_ids != desired_marker_ids:
        markers.clear()
        for marker in session.selected_markers:
            item = item_cls(f"{marker.timestamp_text} | {marker.label} | {marker.note}")
            item.setData(0x0100, marker.marker_id)
            markers.addItem(item)
    panel.refs["export_csv"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_json"].setEnabled(session.selected_session_id is not None)
    panel.refs["export_chart"].setEnabled(bool(session.chart_points))
    panel.refs["chart"].set_data(
        session.chart_points,
        session.marker_points,
        unit_text=session.selected_unit_text,
        measurement_label="Session Replay",
    )


def _refresh_settings(runtime, panel: _PanelRefs) -> None:
    settings = runtime.presenter.settings_view_model()
    panel.refs["database"].setText(f"Database: {settings.database_path_text}")
    panel.refs["diagnostics"].setText(settings.diagnostics_text)
    export_dir_input = panel.refs["export_dir_input"]
    if export_dir_input.text() != settings.export_directory_text:
        export_dir_input.setText(settings.export_directory_text)


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


def _export_chart(runtime, chart, path: Path) -> str:
    exported = chart.export_png(path)
    runtime.presenter.set_export_status(f"Chart image exported to {exported}")
    return exported
