"""Centralized PySide6 imports for the desktop application.

Import from this module instead of PySide6 directly so that:
1. A clear RuntimeError is raised if PySide6 is missing.
2. IDE support (autocompletion, type-checking) works normally.
"""

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtGui import QKeySequence, QShortcut
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QFormLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QListWidget,
        QListWidgetItem,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QTabWidget,
        QTableWidget,
        QTableWidgetItem,
        QTextEdit,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError as _exc:
    raise RuntimeError(
        "PySide6 is required to launch the desktop UI. "
        "Install it with: pip install PySide6"
    ) from _exc

__all__ = [
    "Qt",
    "QTimer",
    "QKeySequence",
    "QShortcut",
    "QAbstractItemView",
    "QApplication",
    "QCheckBox",
    "QComboBox",
    "QDialog",
    "QDialogButtonBox",
    "QFormLayout",
    "QHBoxLayout",
    "QHeaderView",
    "QLabel",
    "QLineEdit",
    "QListWidget",
    "QListWidgetItem",
    "QMainWindow",
    "QMessageBox",
    "QPushButton",
    "QTabWidget",
    "QSpinBox",
    "QTableWidget",
    "QTableWidgetItem",
    "QScrollArea",
    "QTextEdit",
    "QVBoxLayout",
    "QWidget",
]
