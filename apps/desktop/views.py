from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

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
            tabs.addTab(self._home.panel, "Home")
            tabs.addTab(self._discovery.panel, "Device Discovery")
            tabs.addTab(self._live.panel, "Live Reading")
            tabs.addTab(self._session.panel, "Session")
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

    return MainWindow()


def _home_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QLabel = qt["QLabel"]
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
    scan_button = QPushButton("Find Meters")
    scan_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.scan_devices(timeout_s=5.0)))

    for widget in (title, subtitle, connection, device, session, message, scan_button):
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
    title_input = QLineEdit()
    notes_input = QTextEdit()
    notes_input.setFixedHeight(80)
    start_button = QPushButton("Start Logging")
    stop_button = QPushButton("Stop Logging")
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
    disconnect_button.clicked.connect(lambda: _submit(runtime, runtime.presenter.disconnect_device()))

    for widget in (value, unit, measurement, status, connection, last_updated):
        layout.addWidget(widget)
    layout.addLayout(form)
    layout.addWidget(start_button)
    layout.addWidget(stop_button)
    layout.addWidget(disconnect_button)

    return _PanelRefs(
        panel=panel,
        refs={
            "value": value,
            "unit": unit,
            "measurement": measurement,
            "status": status,
            "connection": connection,
            "last_updated": last_updated,
            "title_input": title_input,
            "start_button": start_button,
            "stop_button": stop_button,
        },
    )


def _session_panel(runtime, qt: dict[str, object]) -> _PanelRefs:
    QLabel = qt["QLabel"]
    QListWidget = qt["QListWidget"]
    QListWidgetItem = qt["QListWidgetItem"]
    QPushButton = qt["QPushButton"]
    QWidget = qt["QWidget"]
    QVBoxLayout = qt["QVBoxLayout"]

    panel = QWidget()
    layout = QVBoxLayout(panel)
    active = QLabel()
    count = QLabel()
    database = QLabel()
    export_status = QLabel()
    recent = QListWidget()
    export_csv = QPushButton("Export Last Session CSV")
    export_json = QPushButton("Export Last Session JSON")

    export_csv.clicked.connect(
        lambda: _safe_call(
            runtime,
            lambda: runtime.presenter.export_session_csv("exports/desktop_session.csv"),
        )
    )
    export_json.clicked.connect(
        lambda: _safe_call(
            runtime,
            lambda: runtime.presenter.export_session_json("exports/desktop_session.json"),
        )
    )

    for widget in (active, count, database, export_status, recent, export_csv, export_json):
        layout.addWidget(widget)

    return _PanelRefs(
        panel=panel,
        refs={
            "active": active,
            "count": count,
            "database": database,
            "export_status": export_status,
            "recent": recent,
            "list_item_cls": QListWidgetItem,
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
    panel.refs["last_updated"].setText(f"Last Update: {live.last_updated_text}")
    panel.refs["start_button"].setEnabled(not live.is_logging)
    panel.refs["stop_button"].setEnabled(live.is_logging)
    title_input = panel.refs["title_input"]
    if live.session_title and not title_input.text():
        title_input.setText(live.session_title)


def _refresh_session(runtime, panel: _PanelRefs) -> None:
    session = runtime.presenter.session_view_model()
    panel.refs["active"].setText(f"Active/Last Session: {session.active_title_text}")
    panel.refs["count"].setText(session.reading_count_text)
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
