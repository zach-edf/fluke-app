"""Global QSS stylesheet for the Fluke Community Desktop application.

Color palette derived from the chart widget colors:
- Teal accent:  #0b7a6b (primary actions, active states)
- Orange accent: #ce6a06 (markers, warnings)
- Neutral: grays and off-whites
"""

STYLESHEET = """
/* ── Global ───────────────────────────────────────────── */
QMainWindow, QWidget {
    font-size: 13px;
    color: #1a2b26;
}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {
    padding: 7px 18px;
    border: 1px solid #a0afa8;
    border-radius: 5px;
    background: #e8efec;
    color: #1a2b26;
    font-weight: 500;
}
QPushButton:hover {
    background: #d0ddd8;
    border-color: #0b7a6b;
}
QPushButton:pressed {
    background: #0b7a6b;
    color: white;
    border-color: #065e53;
}
QPushButton:disabled {
    background: #f0f2f1;
    color: #a0afa8;
    border-color: #d6dfdb;
}

/* Primary action buttons (matched by object name) */
QPushButton[objectName="primary_button"] {
    background: #0b7a6b;
    color: white;
    border-color: #065e53;
    font-weight: 600;
}
QPushButton[objectName="primary_button"]:hover {
    background: #099485;
}
QPushButton[objectName="primary_button"]:pressed {
    background: #065e53;
}
QPushButton[objectName="primary_button"]:disabled {
    background: #89b5ae;
    color: #d0e0dc;
    border-color: #89b5ae;
}

/* Danger buttons */
QPushButton[objectName="danger_button"] {
    color: #a83232;
    border-color: #d09090;
}
QPushButton[objectName="danger_button"]:hover {
    background: #fce8e8;
    border-color: #a83232;
}
QPushButton[objectName="danger_button"]:pressed {
    background: #a83232;
    color: white;
}

/* ── Tabs ─────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #d6dfdb;
    border-top: 2px solid #0b7a6b;
    background: white;
}
QTabBar::tab {
    padding: 8px 20px;
    margin-right: 2px;
    border: 1px solid #d6dfdb;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: #f0f2f1;
    color: #4b5b57;
}
QTabBar::tab:selected {
    background: white;
    color: #0b7a6b;
    font-weight: 600;
    border-color: #d6dfdb;
}
QTabBar::tab:hover:!selected {
    background: #e8efec;
}

/* ── Tables ───────────────────────────────────────────── */
QTableWidget {
    border: 1px solid #d6dfdb;
    border-radius: 4px;
    gridline-color: #e8efec;
    background: white;
    alternate-background-color: #f7fbf9;
    selection-background-color: #d4ece7;
    selection-color: #1a2b26;
}
QTableWidget::item {
    padding: 4px 8px;
    color: #1a2b26;
}
QHeaderView::section {
    background: #e8efec;
    color: #4b5b57;
    font-weight: 600;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #d6dfdb;
    border-bottom: 1px solid #d6dfdb;
}

/* ── List Widgets ─────────────────────────────────────── */
QListWidget {
    border: 1px solid #d6dfdb;
    border-radius: 4px;
    background: white;
    selection-background-color: #d4ece7;
    selection-color: #1a2b26;
}
QListWidget::item {
    padding: 4px 8px;
    color: #1a2b26;
}

/* ── Text Inputs ──────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox {
    border: 1px solid #d6dfdb;
    border-radius: 4px;
    padding: 5px 8px;
    background: white;
    color: #1a2b26;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #0b7a6b;
    outline: none;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background: #f0f2f1;
    color: #a0afa8;
}
QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}

/* ── Labels ───────────────────────────────────────────── */
QLabel {
    color: #1a2b26;
}
QLabel[objectName="section_header"] {
    font-weight: 600;
    font-size: 14px;
    color: #0b7a6b;
    padding-top: 4px;
    padding-bottom: 2px;
}
QLabel[objectName="big_reading"] {
    font-size: 42px;
    font-weight: 700;
    color: #0b7a6b;
}
QLabel[objectName="notice_banner"] {
    background: #e8efec;
    color: #0b7a6b;
    border: 1px solid #b9d2cb;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 500;
}
QLabel[objectName="status_ok"] {
    color: #0b7a6b;
}
QLabel[objectName="status_error"] {
    color: #a83232;
}
QLabel[objectName="alert_banner"] {
    background: #fff3e0;
    color: #a83232;
    border: 1px solid #e06060;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 14px;
}
QLabel[objectName="alert_status"] {
    color: #8b4700;
    font-weight: 500;
}

/* ── Status Bar ──────────────────────────────────────── */
QWidget[objectName="status_bar"] {
    background: #f0f2f1;
    border-top: 1px solid #d6dfdb;
}
"""

DARK_STYLESHEET = """
/* ── Global ───────────────────────────────────────────── */
QMainWindow, QWidget {
    font-size: 13px;
    background: #1a2b26;
    color: #d0e0dc;
}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {
    padding: 7px 18px;
    border: 1px solid #3a4f48;
    border-radius: 5px;
    background: #253b35;
    color: #d0e0dc;
    font-weight: 500;
}
QPushButton:hover {
    background: #2f4a42;
    border-color: #0b7a6b;
}
QPushButton:pressed {
    background: #0b7a6b;
    color: white;
    border-color: #099485;
}
QPushButton:disabled {
    background: #1e302b;
    color: #4b5b57;
    border-color: #2a3d37;
}

QPushButton[objectName="primary_button"] {
    background: #0b7a6b;
    color: white;
    border-color: #099485;
    font-weight: 600;
}
QPushButton[objectName="primary_button"]:hover {
    background: #099485;
}
QPushButton[objectName="primary_button"]:pressed {
    background: #0bbda8;
}
QPushButton[objectName="primary_button"]:disabled {
    background: #253b35;
    color: #4b5b57;
    border-color: #253b35;
}

QPushButton[objectName="danger_button"] {
    color: #e06060;
    border-color: #5a2828;
}
QPushButton[objectName="danger_button"]:hover {
    background: #3a1e1e;
    border-color: #e06060;
}
QPushButton[objectName="danger_button"]:pressed {
    background: #a83232;
    color: white;
}

/* ── Tabs ─────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #2a3d37;
    border-top: 2px solid #0b7a6b;
    background: #1a2b26;
}
QTabBar::tab {
    padding: 8px 20px;
    margin-right: 2px;
    border: 1px solid #2a3d37;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: #1e302b;
    color: #8a9e98;
}
QTabBar::tab:selected {
    background: #1a2b26;
    color: #0bbda8;
    font-weight: 600;
    border-color: #2a3d37;
}
QTabBar::tab:hover:!selected {
    background: #253b35;
}

/* ── Tables ───────────────────────────────────────────── */
QTableWidget {
    border: 1px solid #2a3d37;
    border-radius: 4px;
    gridline-color: #253b35;
    background: #1a2b26;
    alternate-background-color: #1e302b;
    selection-background-color: #0b7a6b;
    selection-color: white;
}
QTableWidget::item {
    padding: 4px 8px;
}
QHeaderView::section {
    background: #253b35;
    color: #8a9e98;
    font-weight: 600;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #2a3d37;
    border-bottom: 1px solid #2a3d37;
}

/* ── List Widgets ─────────────────────────────────────── */
QListWidget {
    border: 1px solid #2a3d37;
    border-radius: 4px;
    background: #1a2b26;
    selection-background-color: #0b7a6b;
    selection-color: white;
}
QListWidget::item {
    padding: 4px 8px;
}

/* ── Text Inputs ──────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox {
    border: 1px solid #3a4f48;
    border-radius: 4px;
    padding: 5px 8px;
    background: #253b35;
    color: #d0e0dc;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #0b7a6b;
    outline: none;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background: #1e302b;
    color: #4b5b57;
}
QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}
QComboBox QAbstractItemView {
    background: #253b35;
    color: #d0e0dc;
    selection-background-color: #0b7a6b;
    selection-color: white;
}

/* ── Labels ───────────────────────────────────────────── */
QLabel {
    color: #d0e0dc;
}
QLabel[objectName="section_header"] {
    font-weight: 600;
    font-size: 14px;
    color: #0bbda8;
    padding-top: 4px;
    padding-bottom: 2px;
}
QLabel[objectName="big_reading"] {
    font-size: 42px;
    font-weight: 700;
    color: #0bbda8;
}
QLabel[objectName="notice_banner"] {
    background: #253b35;
    color: #0bbda8;
    border: 1px solid #3a4f48;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 500;
}
QLabel[objectName="status_ok"] {
    color: #0bbda8;
}
QLabel[objectName="status_error"] {
    color: #e06060;
}
QLabel[objectName="alert_banner"] {
    background: #3a1e1e;
    color: #ff6b6b;
    border: 1px solid #5a2828;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 14px;
}
QLabel[objectName="alert_status"] {
    color: #f0b36a;
    font-weight: 500;
}

/* ── Scroll Bars ─────────────────────────────────────── */
QScrollBar:vertical {
    background: #1a2b26;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #3a4f48;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ── Status Bar ──────────────────────────────────────── */
QWidget[objectName="status_bar"] {
    background: #152220;
    border-top: 1px solid #2a3d37;
}
"""
