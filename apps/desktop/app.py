from __future__ import annotations

import asyncio
from math import isfinite
import sys

from apps.desktop._qt import QApplication
from apps.desktop.runtime import build_runtime
from apps.desktop.theme import STYLESHEET
from apps.desktop.views import create_main_window


def run() -> int:
    app = QApplication.instance() or QApplication([])
    _normalize_application_font(app)
    app.setStyleSheet(STYLESHEET)
    if sys.platform == "darwin":
        from PySide6.QtAsyncio import QAsyncioEventLoopPolicy

        previous_policy = asyncio.get_event_loop_policy()
        asyncio.set_event_loop_policy(QAsyncioEventLoopPolicy(quit_qapp=False))
        loop = asyncio.get_event_loop()
        runtime = build_runtime(event_loop=loop)
    else:
        previous_policy = None
        loop = None
        runtime = build_runtime()
    window = create_main_window(runtime)
    window.show()
    try:
        if loop is not None:
            loop.run_forever()
            return 0
        return app.exec()
    finally:
        runtime.close()
        if previous_policy is not None:
            asyncio.set_event_loop_policy(previous_policy)


def _normalize_application_font(app: QApplication) -> None:
    """Ensure Qt has a concrete point-sized base font before applying QSS."""
    font = app.font()
    if font.pointSizeF() > 0:
        return

    point_size = 10.0
    pixel_size = float(font.pixelSize())
    if pixel_size > 0:
        screen = app.primaryScreen()
        dpi = None if screen is None else float(screen.logicalDotsPerInch())
        if dpi is not None and isfinite(dpi) and dpi > 0:
            point_size = pixel_size * 72.0 / dpi

    normalized = app.font()
    normalized.setPointSizeF(max(point_size, 1.0))
    app.setFont(normalized)
