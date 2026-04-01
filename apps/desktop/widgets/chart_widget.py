from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class ReadingChartWidget:
    widget: object
    _chart: object
    _view: object
    _placeholder: object
    _line_series: object
    _comparison_series: object
    _marker_series: object
    _axis_x: object
    _axis_y: object
    _title: str
    _empty_text: str

    def set_data(
        self,
        points: tuple[tuple[float, float], ...] | list[tuple[float, float]],
        marker_points: tuple[tuple[float, float], ...] | list[tuple[float, float]] = (),
        *,
        unit_text: str = "",
        measurement_label: str = "Reading",
        comparison_points: tuple[tuple[float, float], ...] | list[tuple[float, float]] = (),
        comparison_label: str = "Comparison",
    ) -> None:
        numeric_points = [(float(x), float(y)) for x, y in points]
        marker_series_points = [(float(x), float(y)) for x, y in marker_points]
        comparison_series_points = [(float(x), float(y)) for x, y in comparison_points]

        if not numeric_points:
            self._line_series.clear()
            self._comparison_series.clear()
            self._marker_series.clear()
            self._axis_x.setRange(0.0, 1.0)
            self._axis_y.setRange(0.0, 1.0)
            self._axis_y.setTitleText(unit_text or "Value")
            self._chart.setTitle(self._title)
            self._chart.legend().hide()
            self._placeholder.setText(self._empty_text)
            self._placeholder.show()
            self._view.hide()
            return

        self._line_series.clear()
        self._line_series.setName("Selected Session")
        for x_value, y_value in numeric_points:
            self._line_series.append(x_value, y_value)

        self._comparison_series.clear()
        self._comparison_series.setName(comparison_label or "Comparison")
        for x_value, y_value in comparison_series_points:
            self._comparison_series.append(x_value, y_value)

        self._marker_series.clear()
        for x_value, y_value in marker_series_points:
            self._marker_series.append(x_value, y_value)

        xs = [point[0] for point in numeric_points] + [point[0] for point in comparison_series_points]
        ys = [point[1] for point in numeric_points] + [point[1] for point in comparison_series_points]
        min_x = min(xs)
        max_x = max(xs)
        min_y = min(ys)
        max_y = max(ys)

        if min_x == max_x:
            max_x = min_x + 1.0
        padding_y = max((max_y - min_y) * 0.1, abs(max_y) * 0.05, 0.5)
        if min_y == max_y:
            min_y -= padding_y
            max_y += padding_y
        else:
            min_y -= padding_y
            max_y += padding_y

        y_label = unit_text or "Value"
        title = self._title if not measurement_label or measurement_label == "Idle" else f"{self._title} - {measurement_label}"
        self._chart.setTitle(title)
        self._axis_x.setRange(min(0.0, min_x), max_x)
        self._axis_y.setRange(min_y, max_y)
        self._axis_y.setTitleText(y_label)
        self._chart.legend().setVisible(bool(comparison_series_points))
        self._placeholder.hide()
        self._view.show()

    def export_png(self, path: str | Path) -> str:
        if self._line_series.count() == 0:
            raise RuntimeError("No chart data is available to export yet.")

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not self._view.grab().save(str(target), "PNG"):
            raise RuntimeError(f"Failed to export chart image to {target}.")
        return str(target)


def build_reading_chart(
    *,
    title: str,
    empty_text: str,
    minimum_height: int = 260,
) -> ReadingChartWidget:
    try:
        from PySide6.QtCharts import QChart, QChartView, QLineSeries, QScatterSeries, QValueAxis
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter, QPen
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySide6 with QtCharts is required to render charts.") from exc

    container = QWidget()
    container.setMinimumHeight(minimum_height)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    placeholder = QLabel(empty_text)
    placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    placeholder.setMinimumHeight(minimum_height)
    placeholder.setStyleSheet(
        "border: 1px solid #d6dfdb; border-radius: 8px; background: #f5f8f6; color: #4b5b57; padding: 16px;"
    )

    chart = QChart()
    chart.setTitle(title)
    chart.legend().hide()
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(True)
    chart.setPlotAreaBackgroundBrush(QColor("#f7fbf9"))
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

    line_series = QLineSeries()
    line_series.setName("Reading")
    line_series.setColor(QColor("#0b7a6b"))
    chart.addSeries(line_series)

    comparison_series = QLineSeries()
    comparison_series.setName("Comparison")
    comparison_pen = QPen(QColor("#ce6a06"))
    comparison_pen.setStyle(Qt.PenStyle.DashLine)
    comparison_pen.setWidth(2)
    comparison_series.setPen(comparison_pen)
    chart.addSeries(comparison_series)

    marker_series = QScatterSeries()
    marker_series.setName("Markers")
    marker_series.setMarkerSize(11.0)
    marker_series.setColor(QColor("#ce6a06"))
    marker_series.setBorderColor(QColor("#8b4700"))
    chart.addSeries(marker_series)

    axis_x = QValueAxis()
    axis_x.setTitleText("Seconds")
    axis_x.setLabelFormat("%.1f")
    axis_x.setRange(0.0, 1.0)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    line_series.attachAxis(axis_x)
    comparison_series.attachAxis(axis_x)
    marker_series.attachAxis(axis_x)

    axis_y = QValueAxis()
    axis_y.setTitleText("Value")
    axis_y.setLabelFormat("%.4g")
    axis_y.setRange(0.0, 1.0)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    line_series.attachAxis(axis_y)
    comparison_series.attachAxis(axis_y)
    marker_series.attachAxis(axis_y)

    view = QChartView(chart)
    view.setMinimumHeight(minimum_height)
    view.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    view.hide()

    layout.addWidget(placeholder)
    layout.addWidget(view)

    return ReadingChartWidget(
        widget=container,
        _chart=chart,
        _view=view,
        _placeholder=placeholder,
        _line_series=line_series,
        _comparison_series=comparison_series,
        _marker_series=marker_series,
        _axis_x=axis_x,
        _axis_y=axis_y,
        _title=title,
        _empty_text=empty_text,
    )


__all__ = ["ReadingChartWidget", "build_reading_chart"]
