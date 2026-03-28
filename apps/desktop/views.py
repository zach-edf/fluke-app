from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


def _require_qt():
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import (
            QApplication,
            QHBoxLayout,
            QLabel,
            QMainWindow,
            QPushButton,
            QStackedWidget,
            QTabWidget,
            QVBoxLayout,
            QWidget,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySide6 is required to launch the desktop UI.") from exc

    return {
        "Qt": Qt,
        "QApplication": QApplication,
        "QHBoxLayout": QHBoxLayout,
        "QLabel": QLabel,
        "QMainWindow": QMainWindow,
        "QPushButton": QPushButton,
        "QStackedWidget": QStackedWidget,
        "QTabWidget": QTabWidget,
        "QVBoxLayout": QVBoxLayout,
        "QWidget": QWidget,
    }


def create_main_window(runtime) -> "QWidget":
    qt = _require_qt()
    QWidget = qt["QWidget"]
    QMainWindow = qt["QMainWindow"]
    QVBoxLayout = qt["QVBoxLayout"]
    QHBoxLayout = qt["QHBoxLayout"]
    QLabel = qt["QLabel"]
    QPushButton = qt["QPushButton"]
    QTabWidget = qt["QTabWidget"]
    QStackedWidget = qt["QStackedWidget"]
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
            tabs.addTab(_home_panel(runtime, QStackedWidget, QLabel, QPushButton, QWidget, QVBoxLayout), "Home")
            tabs.addTab(_discovery_panel(QLabel, QPushButton, QWidget, QVBoxLayout), "Device Discovery")
            tabs.addTab(_live_panel(runtime, QLabel, QPushButton, QWidget, QVBoxLayout), "Live Reading")
            tabs.addTab(_session_panel(QLabel, QWidget, QVBoxLayout), "Session")
            outer.addWidget(tabs)

            self.setCentralWidget(root)

    return MainWindow()


def _home_panel(runtime, QStackedWidget, QLabel, QPushButton, QWidget, QVBoxLayout):
    panel = QWidget()
    layout = QVBoxLayout(panel)
    home = runtime.presenter.home_view_model()
    layout.addWidget(QLabel(home.title))
    layout.addWidget(QLabel(home.subtitle))
    layout.addWidget(QLabel(f"Connection: {home.connection_text}"))
    layout.addWidget(QLabel(f"Session: {home.active_session_text}"))
    layout.addWidget(QPushButton("Find Meters"))
    layout.addWidget(QPushButton("Start Logging"))
    return panel


def _discovery_panel(QLabel, QPushButton, QWidget, QVBoxLayout):
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.addWidget(QLabel("Scan for nearby meters and select a known or experimental device."))
    layout.addWidget(QPushButton("Scan"))
    layout.addWidget(QPushButton("Connect"))
    return panel


def _live_panel(runtime, QLabel, QPushButton, QWidget, QVBoxLayout):
    panel = QWidget()
    layout = QVBoxLayout(panel)
    live = runtime.presenter.live_view_model()
    layout.addWidget(QLabel(live.main_value))
    layout.addWidget(QLabel(live.unit_text))
    layout.addWidget(QLabel(live.measurement_label))
    layout.addWidget(QLabel(live.status_text))
    layout.addWidget(QLabel(live.connection_text))
    layout.addWidget(QPushButton("Start Logging"))
    layout.addWidget(QPushButton("Stop Logging"))
    return panel


def _session_panel(QLabel, QWidget, QVBoxLayout):
    panel = QWidget()
    layout = QVBoxLayout(panel)
    layout.addWidget(QLabel("Session metadata, tags, and export controls will live here."))
    return panel

