from __future__ import annotations

import asyncio
import sys

from apps.desktop._qt import QApplication
from apps.desktop.runtime import build_runtime
from apps.desktop.theme import STYLESHEET
from apps.desktop.views import create_main_window


def run() -> int:
    app = QApplication.instance() or QApplication([])
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
