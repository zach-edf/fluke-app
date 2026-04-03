from __future__ import annotations

import os
from pathlib import Path
import unittest
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from apps.desktop._qt import QApplication
from apps.desktop.widgets import build_reading_chart


class DesktopChartWidgetTests(unittest.TestCase):
    def test_chart_widget_exports_png(self) -> None:
        tmp_root = Path(__file__).resolve().parents[2] / ".test-tmp"
        tmp = tmp_root / uuid4().hex
        tmp.mkdir(parents=True, exist_ok=False)

        app = QApplication.instance() or QApplication([])
        chart = build_reading_chart(title="Live Reading", empty_text="No data yet.")

        try:
            chart.set_data(
                ((0.0, 12.34), (1.0, 12.56), (2.0, 12.41)),
                ((1.0, 12.56),),
                unit_text="V",
                measurement_label="Voltage Dc",
            )
            exported = Path(chart.export_png(tmp / "chart.png"))
            self.assertTrue(exported.exists())
            self.assertGreater(exported.stat().st_size, 0)
        finally:
            chart.widget.close()
            if app is not None:
                app.processEvents()


if __name__ == "__main__":
    unittest.main()
