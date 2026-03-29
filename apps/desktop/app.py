from __future__ import annotations

import asyncio
import sys

from PySide6.QtAsyncio import QAsyncioEventLoopPolicy

from apps.desktop.runtime import build_runtime
from apps.desktop.views import _require_qt, create_main_window


def run() -> int:
    qt = _require_qt()
    QApplication = qt["QApplication"]

    app = QApplication.instance() or QApplication([])
    if sys.platform == "darwin":
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
