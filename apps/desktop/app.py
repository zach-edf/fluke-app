from __future__ import annotations

from apps.desktop.runtime import build_runtime
from apps.desktop.views import _require_qt, create_main_window


def run() -> int:
    qt = _require_qt()
    QApplication = qt["QApplication"]

    app = QApplication.instance() or QApplication([])
    runtime = build_runtime()
    window = create_main_window(runtime)
    window.show()
    return app.exec()

