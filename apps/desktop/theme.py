"""Global QSS stylesheets for the Fluke Community Desktop application.

Three themes:
  - LIGHT_STYLESHEET:  Neutral white/gray, minimal color. Default.
  - DARK_STYLESHEET:   Neutral charcoal/slate, minimal color.
  - FLUKE_STYLESHEET:  Dark charcoal + Fluke yellow (#F5A623) accent. Branded.

Accent color is reserved for: active tab, primary buttons, selected rows,
section headers, live reading value, and chart line.  Everything else is neutral.
"""

# ---------------------------------------------------------------------------
# Palette tokens (not used at runtime — reference for the QSS below)
# ---------------------------------------------------------------------------
# LIGHT                          DARK                           FLUKE
# bg:        #FFFFFF             bg:        #0F1419             bg:        #1A1A1A
# surface:   #F8F9FA             surface:   #161B22             surface:   #242424
# elevated:  #F1F3F5             elevated:  #1C2128             elevated:  #2E2E2E
# border:    #D1D5DB             border:    #2D333B             border:    #3D3D3D
# text:      #1F2937             text:      #E6EDF3             text:      #E8E8E8
# muted:     #6B7280             muted:     #8B949E             muted:     #9E9E9E
# accent:    #2563EB             accent:    #58A6FF             accent:    #F5A623
# accentHov: #1D4ED8             accentHov: #79C0FF             accentHov: #FFBD45
# success:   #16A34A             success:   #3FB950             success:   #3FB950
# danger:    #DC2626             danger:    #F85149             danger:    #F85149
# warn:      #D97706             warn:      #D29922             warn:      #D29922
# ---------------------------------------------------------------------------

# ═══════════════════════════════════════════════════════════════════════════
#  LIGHT
# ═══════════════════════════════════════════════════════════════════════════

STYLESHEET = """
/* ── Global ───────────────────────────────────────────── */
QMainWindow, QWidget {
    font-size: 13px;
    color: #1F2937;
    background: #FFFFFF;
}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {
    padding: 7px 18px;
    border: 1px solid #D1D5DB;
    border-radius: 6px;
    background: #F8F9FA;
    color: #1F2937;
    font-weight: 500;
}
QPushButton:hover {
    background: #F1F3F5;
    border-color: #9CA3AF;
}
QPushButton:pressed {
    background: #E5E7EB;
}
QPushButton:disabled {
    background: #F8F9FA;
    color: #9CA3AF;
    border-color: #E5E7EB;
}

QPushButton[objectName="primary_button"] {
    background: #2563EB;
    color: white;
    border-color: #1D4ED8;
    font-weight: 600;
}
QPushButton[objectName="primary_button"]:hover {
    background: #1D4ED8;
}
QPushButton[objectName="primary_button"]:pressed {
    background: #1E40AF;
}
QPushButton[objectName="primary_button"]:disabled {
    background: #93C5FD;
    color: #DBEAFE;
    border-color: #93C5FD;
}

QPushButton[objectName="danger_button"] {
    color: #DC2626;
    border-color: #FCA5A5;
}
QPushButton[objectName="danger_button"]:hover {
    background: #FEF2F2;
    border-color: #DC2626;
}
QPushButton[objectName="danger_button"]:pressed {
    background: #DC2626;
    color: white;
}

/* ── Tabs ─────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #D1D5DB;
    border-top: 2px solid #2563EB;
    background: #FFFFFF;
}
QTabBar::tab {
    padding: 8px 20px;
    margin-right: 2px;
    border: 1px solid #D1D5DB;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: #F1F3F5;
    color: #6B7280;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #2563EB;
    font-weight: 600;
    border-color: #D1D5DB;
}
QTabBar::tab:hover:!selected {
    background: #E5E7EB;
}

/* ── Tables ───────────────────────────────────────────── */
QTableWidget {
    border: 1px solid #D1D5DB;
    border-radius: 4px;
    gridline-color: #E5E7EB;
    background: #FFFFFF;
    alternate-background-color: #F8F9FA;
    selection-background-color: #DBEAFE;
    selection-color: #1F2937;
}
QTableWidget::item {
    padding: 4px 8px;
    color: #1F2937;
}
QHeaderView::section {
    background: #F1F3F5;
    color: #6B7280;
    font-weight: 600;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #D1D5DB;
    border-bottom: 1px solid #D1D5DB;
}

/* ── List Widgets ─────────────────────────────────────── */
QListWidget {
    border: 1px solid #D1D5DB;
    border-radius: 4px;
    background: #FFFFFF;
    selection-background-color: #DBEAFE;
    selection-color: #1F2937;
}
QListWidget::item {
    padding: 4px 8px;
    color: #1F2937;
}

/* ── Text Inputs ──────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox {
    border: 1px solid #D1D5DB;
    border-radius: 4px;
    padding: 5px 8px;
    background: #FFFFFF;
    color: #1F2937;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #2563EB;
    outline: none;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background: #F1F3F5;
    color: #9CA3AF;
}
QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}
QComboBox QAbstractItemView {
    background: #FFFFFF;
    color: #1F2937;
    selection-background-color: #DBEAFE;
    selection-color: #1F2937;
}

/* ── Labels ───────────────────────────────────────────── */
QCheckBox {
    spacing: 8px;
    color: #1F2937;
    font-weight: 500;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #9CA3AF;
    border-radius: 3px;
    background: #FFFFFF;
}
QCheckBox::indicator:hover {
    border-color: #2563EB;
}
QCheckBox::indicator:checked {
    background: #2563EB;
    border-color: #1D4ED8;
}
QCheckBox::indicator:unchecked:disabled,
QCheckBox::indicator:checked:disabled {
    background: #F1F3F5;
    border-color: #D1D5DB;
}
QLabel {
    color: #1F2937;
}
QLabel[objectName="section_header"] {
    font-weight: 600;
    font-size: 15px;
    color: #2563EB;
    padding-top: 4px;
    padding-bottom: 2px;
}
QLabel[objectName="big_reading"] {
    font-size: 56px;
    font-weight: 700;
    color: #1F2937;
}
QLabel[objectName="notice_banner"] {
    background: #EFF6FF;
    color: #1D4ED8;
    border: 1px solid #BFDBFE;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 500;
}
QLabel[objectName="status_ok"] {
    color: #16A34A;
}
QLabel[objectName="status_error"] {
    color: #DC2626;
}
QLabel[objectName="alert_banner"] {
    background: #FEF2F2;
    color: #DC2626;
    border: 1px solid #FECACA;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 14px;
}
QLabel[objectName="alert_status"] {
    color: #D97706;
    font-weight: 500;
}

/* ── Scroll Bars ─────────────────────────────────────── */
QScrollBar:vertical {
    background: #F8F9FA;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #D1D5DB;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #9CA3AF;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ── Status Bar ──────────────────────────────────────── */
QWidget[objectName="status_bar"] {
    background: #F1F3F5;
    border-top: 1px solid #D1D5DB;
}
"""

# ═══════════════════════════════════════════════════════════════════════════
#  DARK
# ═══════════════════════════════════════════════════════════════════════════

DARK_STYLESHEET = """
/* ── Global ───────────────────────────────────────────── */
QMainWindow, QWidget {
    font-size: 13px;
    background: #0F1419;
    color: #E6EDF3;
}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {
    padding: 7px 18px;
    border: 1px solid #2D333B;
    border-radius: 6px;
    background: #161B22;
    color: #E6EDF3;
    font-weight: 500;
}
QPushButton:hover {
    background: #1C2128;
    border-color: #444C56;
}
QPushButton:pressed {
    background: #272E36;
}
QPushButton:disabled {
    background: #161B22;
    color: #484F58;
    border-color: #21262D;
}

QPushButton[objectName="primary_button"] {
    background: #2563EB;
    color: white;
    border-color: #1D4ED8;
    font-weight: 600;
}
QPushButton[objectName="primary_button"]:hover {
    background: #3B82F6;
}
QPushButton[objectName="primary_button"]:pressed {
    background: #1D4ED8;
}
QPushButton[objectName="primary_button"]:disabled {
    background: #1C2128;
    color: #484F58;
    border-color: #1C2128;
}

QPushButton[objectName="danger_button"] {
    color: #F85149;
    border-color: #3D1E20;
}
QPushButton[objectName="danger_button"]:hover {
    background: #2D1215;
    border-color: #F85149;
}
QPushButton[objectName="danger_button"]:pressed {
    background: #DA3633;
    color: white;
}

/* ── Tabs ─────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #2D333B;
    border-top: 2px solid #58A6FF;
    background: #0F1419;
}
QTabBar::tab {
    padding: 8px 20px;
    margin-right: 2px;
    border: 1px solid #2D333B;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: #161B22;
    color: #8B949E;
}
QTabBar::tab:selected {
    background: #0F1419;
    color: #58A6FF;
    font-weight: 600;
    border-color: #2D333B;
}
QTabBar::tab:hover:!selected {
    background: #1C2128;
}

/* ── Tables ───────────────────────────────────────────── */
QTableWidget {
    border: 1px solid #2D333B;
    border-radius: 4px;
    gridline-color: #21262D;
    background: #0F1419;
    alternate-background-color: #131920;
    selection-background-color: #1A3A5C;
    selection-color: #E6EDF3;
}
QTableWidget::item {
    padding: 4px 8px;
    color: #E6EDF3;
}
QHeaderView::section {
    background: #161B22;
    color: #8B949E;
    font-weight: 600;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #2D333B;
    border-bottom: 1px solid #2D333B;
}

/* ── List Widgets ─────────────────────────────────────── */
QListWidget {
    border: 1px solid #2D333B;
    border-radius: 4px;
    background: #0F1419;
    selection-background-color: #1A3A5C;
    selection-color: #E6EDF3;
}
QListWidget::item {
    padding: 4px 8px;
    color: #E6EDF3;
}

/* ── Text Inputs ──────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox {
    border: 1px solid #2D333B;
    border-radius: 4px;
    padding: 5px 8px;
    background: #161B22;
    color: #E6EDF3;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #58A6FF;
    outline: none;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background: #0F1419;
    color: #484F58;
}
QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}
QComboBox QAbstractItemView {
    background: #161B22;
    color: #E6EDF3;
    selection-background-color: #1A3A5C;
    selection-color: #E6EDF3;
}

/* ── Labels ───────────────────────────────────────────── */
QCheckBox {
    spacing: 8px;
    color: #E6EDF3;
    font-weight: 500;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #444C56;
    border-radius: 3px;
    background: #161B22;
}
QCheckBox::indicator:hover {
    border-color: #58A6FF;
}
QCheckBox::indicator:checked {
    background: #58A6FF;
    border-color: #58A6FF;
}
QCheckBox::indicator:unchecked:disabled,
QCheckBox::indicator:checked:disabled {
    background: #0F1419;
    border-color: #2D333B;
}
QLabel {
    color: #E6EDF3;
}
QLabel[objectName="section_header"] {
    font-weight: 600;
    font-size: 15px;
    color: #58A6FF;
    padding-top: 4px;
    padding-bottom: 2px;
}
QLabel[objectName="big_reading"] {
    font-size: 56px;
    font-weight: 700;
    color: #E6EDF3;
}
QLabel[objectName="notice_banner"] {
    background: #161B22;
    color: #58A6FF;
    border: 1px solid #2D333B;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 500;
}
QLabel[objectName="status_ok"] {
    color: #3FB950;
}
QLabel[objectName="status_error"] {
    color: #F85149;
}
QLabel[objectName="alert_banner"] {
    background: #2D1215;
    color: #F85149;
    border: 1px solid #3D1E20;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 14px;
}
QLabel[objectName="alert_status"] {
    color: #D29922;
    font-weight: 500;
}

/* ── Scroll Bars ─────────────────────────────────────── */
QScrollBar:vertical {
    background: #0F1419;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #2D333B;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #444C56;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ── Status Bar ──────────────────────────────────────── */
QWidget[objectName="status_bar"] {
    background: #0D1117;
    border-top: 1px solid #2D333B;
}
"""

# ═══════════════════════════════════════════════════════════════════════════
#  FLUKE (branded — Fluke yellow on dark charcoal)
# ═══════════════════════════════════════════════════════════════════════════

FLUKE_STYLESHEET = """
/* ── Global ───────────────────────────────────────────── */
QMainWindow, QWidget {
    font-size: 13px;
    background: #1A1A1A;
    color: #E8E8E8;
}

/* ── Buttons ──────────────────────────────────────────── */
QPushButton {
    padding: 7px 18px;
    border: 1px solid #3D3D3D;
    border-radius: 6px;
    background: #242424;
    color: #E8E8E8;
    font-weight: 500;
}
QPushButton:hover {
    background: #2E2E2E;
    border-color: #505050;
}
QPushButton:pressed {
    background: #383838;
}
QPushButton:disabled {
    background: #1E1E1E;
    color: #585858;
    border-color: #2A2A2A;
}

QPushButton[objectName="primary_button"] {
    background: #F5A623;
    color: #1A1A1A;
    border-color: #D4901E;
    font-weight: 600;
}
QPushButton[objectName="primary_button"]:hover {
    background: #FFBD45;
}
QPushButton[objectName="primary_button"]:pressed {
    background: #D4901E;
}
QPushButton[objectName="primary_button"]:disabled {
    background: #3D3D3D;
    color: #585858;
    border-color: #3D3D3D;
}

QPushButton[objectName="danger_button"] {
    color: #F85149;
    border-color: #3D1E20;
}
QPushButton[objectName="danger_button"]:hover {
    background: #2D1215;
    border-color: #F85149;
}
QPushButton[objectName="danger_button"]:pressed {
    background: #DA3633;
    color: white;
}

/* ── Tabs ─────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #3D3D3D;
    border-top: 2px solid #F5A623;
    background: #1A1A1A;
}
QTabBar::tab {
    padding: 8px 20px;
    margin-right: 2px;
    border: 1px solid #3D3D3D;
    border-bottom: none;
    border-top-left-radius: 5px;
    border-top-right-radius: 5px;
    background: #242424;
    color: #9E9E9E;
}
QTabBar::tab:selected {
    background: #1A1A1A;
    color: #F5A623;
    font-weight: 600;
    border-color: #3D3D3D;
}
QTabBar::tab:hover:!selected {
    background: #2E2E2E;
}

/* ── Tables ───────────────────────────────────────────── */
QTableWidget {
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    gridline-color: #2A2A2A;
    background: #1A1A1A;
    alternate-background-color: #1F1F1F;
    selection-background-color: #3D2E10;
    selection-color: #F5A623;
}
QTableWidget::item {
    padding: 4px 8px;
    color: #E8E8E8;
}
QHeaderView::section {
    background: #242424;
    color: #9E9E9E;
    font-weight: 600;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #3D3D3D;
    border-bottom: 1px solid #3D3D3D;
}

/* ── List Widgets ─────────────────────────────────────── */
QListWidget {
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    background: #1A1A1A;
    selection-background-color: #3D2E10;
    selection-color: #F5A623;
}
QListWidget::item {
    padding: 4px 8px;
    color: #E8E8E8;
}

/* ── Text Inputs ──────────────────────────────────────── */
QLineEdit, QTextEdit, QComboBox {
    border: 1px solid #3D3D3D;
    border-radius: 4px;
    padding: 5px 8px;
    background: #242424;
    color: #E8E8E8;
}
QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border-color: #F5A623;
    outline: none;
}
QLineEdit:disabled, QTextEdit:disabled, QComboBox:disabled {
    background: #1A1A1A;
    color: #585858;
}
QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}
QComboBox QAbstractItemView {
    background: #242424;
    color: #E8E8E8;
    selection-background-color: #3D2E10;
    selection-color: #F5A623;
}

/* ── Labels ───────────────────────────────────────────── */
QCheckBox {
    spacing: 8px;
    color: #E8E8E8;
    font-weight: 500;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #505050;
    border-radius: 3px;
    background: #242424;
}
QCheckBox::indicator:hover {
    border-color: #F5A623;
}
QCheckBox::indicator:checked {
    background: #F5A623;
    border-color: #D4901E;
}
QCheckBox::indicator:unchecked:disabled,
QCheckBox::indicator:checked:disabled {
    background: #1A1A1A;
    border-color: #3D3D3D;
}
QLabel {
    color: #E8E8E8;
}
QLabel[objectName="section_header"] {
    font-weight: 600;
    font-size: 15px;
    color: #F5A623;
    padding-top: 4px;
    padding-bottom: 2px;
}
QLabel[objectName="big_reading"] {
    font-size: 56px;
    font-weight: 700;
    color: #F5A623;
}
QLabel[objectName="notice_banner"] {
    background: #242424;
    color: #F5A623;
    border: 1px solid #3D3D3D;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 500;
}
QLabel[objectName="status_ok"] {
    color: #3FB950;
}
QLabel[objectName="status_error"] {
    color: #F85149;
}
QLabel[objectName="alert_banner"] {
    background: #2D1215;
    color: #F85149;
    border: 1px solid #3D1E20;
    border-radius: 5px;
    padding: 6px 10px;
    font-weight: 600;
    font-size: 14px;
}
QLabel[objectName="alert_status"] {
    color: #D29922;
    font-weight: 500;
}

/* ── Scroll Bars ─────────────────────────────────────── */
QScrollBar:vertical {
    background: #1A1A1A;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #3D3D3D;
    min-height: 20px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #505050;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

/* ── Status Bar ──────────────────────────────────────── */
QWidget[objectName="status_bar"] {
    background: #141414;
    border-top: 1px solid #3D3D3D;
}
"""

# ---------------------------------------------------------------------------
# Theme registry — used by views.py for theme switching and by chart_widget
# for adapting plot colors.
# ---------------------------------------------------------------------------

THEMES: dict[str, dict] = {
    "light": {
        "label": "Light",
        "stylesheet": STYLESHEET,
        "chart_bg": "#F8F9FA",
        "chart_plot_bg": "#FFFFFF",
        "chart_line": "#2563EB",
        "chart_comparison": "#D97706",
        "chart_marker": "#D97706",
        "chart_marker_border": "#92400E",
        "chart_grid": "#E5E7EB",
        "chart_axis_label": "#6B7280",
        "chart_title": "#1F2937",
        "status_bar_text": "#6B7280",
    },
    "dark": {
        "label": "Dark",
        "stylesheet": DARK_STYLESHEET,
        "chart_bg": "#0F1419",
        "chart_plot_bg": "#131920",
        "chart_line": "#58A6FF",
        "chart_comparison": "#D29922",
        "chart_marker": "#D29922",
        "chart_marker_border": "#92400E",
        "chart_grid": "#21262D",
        "chart_axis_label": "#8B949E",
        "chart_title": "#E6EDF3",
        "status_bar_text": "#8B949E",
    },
    "fluke": {
        "label": "Fluke",
        "stylesheet": FLUKE_STYLESHEET,
        "chart_bg": "#1A1A1A",
        "chart_plot_bg": "#1F1F1F",
        "chart_line": "#F5A623",
        "chart_comparison": "#58A6FF",
        "chart_marker": "#F5A623",
        "chart_marker_border": "#92400E",
        "chart_grid": "#2A2A2A",
        "chart_axis_label": "#9E9E9E",
        "chart_title": "#E8E8E8",
        "status_bar_text": "#9E9E9E",
    },
}

# The active theme ID — updated by the settings panel when the user switches.
active_theme: str = "light"
