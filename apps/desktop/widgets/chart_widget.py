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
    _axis_x_value: object
    _axis_x_time: object
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
        x_axis_mode: str = "elapsed",
        x_axis_title: str = "Seconds",
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
            self._axis_x_value.setRange(0.0, 1.0)
            self._axis_y.setRange(0.0, 1.0)
            self._axis_y.setTitleText(unit_text or "Value")
            self._axis_x_value.setTitleText(x_axis_title)
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
        self._apply_x_axis(x_axis_mode, x_axis_title, min_x, max_x)
        self._axis_y.setRange(min_y, max_y)
        self._axis_y.setTitleText(y_label)
        self._chart.legend().setVisible(bool(comparison_series_points))
        self._placeholder.hide()
        self._view.show()

    def _apply_x_axis(self, x_axis_mode: str, x_axis_title: str, min_x: float, max_x: float) -> None:
        from PySide6.QtCore import QDateTime

        use_time_axis = x_axis_mode == "datetime"
        self._axis_x_value.setVisible(not use_time_axis)
        self._axis_x_time.setVisible(use_time_axis)
        self._axis_x_value.setTitleText(x_axis_title)
        self._axis_x_time.setTitleText(x_axis_title)
        for series in (self._line_series, self._comparison_series, self._marker_series):
            try:
                series.detachAxis(self._axis_x_value)
            except Exception:
                pass
            try:
                series.detachAxis(self._axis_x_time)
            except Exception:
                pass
            series.attachAxis(self._axis_x_time if use_time_axis else self._axis_x_value)
        if use_time_axis:
            if min_x == max_x:
                max_x = min_x + 1000.0
            self._axis_x_time.setRange(
                QDateTime.fromMSecsSinceEpoch(int(min_x)),
                QDateTime.fromMSecsSinceEpoch(int(max_x)),
            )
        else:
            self._axis_x_value.setRange(min(0.0, min_x), max_x)

    def apply_theme(self, theme_colors: dict[str, str]) -> None:
        """Update chart colors to match the active theme."""
        from PySide6.QtGui import QColor, QPen
        from PySide6.QtCore import Qt

        bg = theme_colors.get("chart_bg", "#FFFFFF")
        plot_bg = theme_colors.get("chart_plot_bg", "#FFFFFF")
        line = theme_colors.get("chart_line", "#2563EB")
        comparison = theme_colors.get("chart_comparison", "#D97706")
        marker = theme_colors.get("chart_marker", "#D97706")
        marker_border = theme_colors.get("chart_marker_border", "#92400E")
        grid = theme_colors.get("chart_grid", "#E5E7EB")
        axis_label = theme_colors.get("chart_axis_label", "#6B7280")
        title_color = theme_colors.get("chart_title", "#1F2937")

        is_dark = bg != "#FFFFFF" and bg.startswith("#") and int(bg[1:3], 16) < 0x40

        # Chart background
        self._chart.setPlotAreaBackgroundBrush(QColor(plot_bg))
        self._view.setBackgroundBrush(QColor(bg))

        # Title
        self._chart.setTitleBrush(QColor(title_color))

        # Line series
        self._line_series.setColor(QColor(line))

        # Comparison series
        comp_pen = QPen(QColor(comparison))
        comp_pen.setStyle(Qt.PenStyle.DashLine)
        comp_pen.setWidth(2)
        self._comparison_series.setPen(comp_pen)

        # Marker series
        self._marker_series.setColor(QColor(marker))
        self._marker_series.setBorderColor(QColor(marker_border))

        # Axes
        axis_brush = QColor(axis_label)
        grid_pen = QPen(QColor(grid))
        for axis in (self._axis_x_value, self._axis_x_time, self._axis_y):
            axis.setLabelsColor(axis_brush)
            axis.setTitleBrush(axis_brush)
            axis.setGridLinePen(grid_pen)
            axis.setLinePen(QPen(QColor(grid)))

        # Placeholder (adapt to light/dark)
        if is_dark:
            border = grid
            surface = plot_bg
            text = axis_label
        else:
            border = "#D1D5DB"
            surface = "#F8F9FA"
            text = "#6B7280"
        self._placeholder.setStyleSheet(
            f"border: 1px solid {border}; border-radius: 8px; "
            f"background: {surface}; color: {text}; padding: 16px;"
        )

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
        from PySide6.QtCharts import QChart, QChartView, QDateTimeAxis, QLineSeries, QScatterSeries, QValueAxis
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QColor, QPainter, QPen
        from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget
    except ModuleNotFoundError as exc:
        raise RuntimeError("PySide6 with QtCharts is required to render charts.") from exc

    from apps.desktop.theme import THEMES, active_theme
    colors = THEMES.get(active_theme, THEMES["light"])

    container = QWidget()
    container.setMinimumHeight(minimum_height)
    layout = QVBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)

    placeholder = QLabel(empty_text)
    placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
    placeholder.setMinimumHeight(minimum_height)
    placeholder.setStyleSheet(
        "border: 1px solid #D1D5DB; border-radius: 8px; background: #F8F9FA; color: #6B7280; padding: 16px;"
    )

    chart = QChart()
    chart.setTitle(title)
    chart.legend().hide()
    chart.setBackgroundVisible(False)
    chart.setPlotAreaBackgroundVisible(True)
    chart.setPlotAreaBackgroundBrush(QColor(colors["chart_plot_bg"]))
    chart.setAnimationOptions(QChart.AnimationOption.NoAnimation)

    line_series = QLineSeries()
    line_series.setName("Reading")
    line_series.setColor(QColor(colors["chart_line"]))
    chart.addSeries(line_series)

    comparison_series = QLineSeries()
    comparison_series.setName("Comparison")
    comparison_pen = QPen(QColor(colors["chart_comparison"]))
    comparison_pen.setStyle(Qt.PenStyle.DashLine)
    comparison_pen.setWidth(2)
    comparison_series.setPen(comparison_pen)
    chart.addSeries(comparison_series)

    marker_series = QScatterSeries()
    marker_series.setName("Markers")
    marker_series.setMarkerSize(11.0)
    marker_series.setColor(QColor(colors["chart_marker"]))
    marker_series.setBorderColor(QColor(colors["chart_marker_border"]))
    chart.addSeries(marker_series)

    axis_x_value = QValueAxis()
    axis_x_value.setTitleText("Seconds")
    axis_x_value.setLabelFormat("%.1f")
    axis_x_value.setRange(0.0, 1.0)
    chart.addAxis(axis_x_value, Qt.AlignmentFlag.AlignBottom)
    line_series.attachAxis(axis_x_value)
    comparison_series.attachAxis(axis_x_value)
    marker_series.attachAxis(axis_x_value)

    axis_x_time = QDateTimeAxis()
    axis_x_time.setTitleText("UTC")
    axis_x_time.setFormat("HH:mm:ss")
    axis_x_time.setVisible(False)
    chart.addAxis(axis_x_time, Qt.AlignmentFlag.AlignBottom)

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

    widget = ReadingChartWidget(
        widget=container,
        _chart=chart,
        _view=view,
        _placeholder=placeholder,
        _line_series=line_series,
        _comparison_series=comparison_series,
        _marker_series=marker_series,
        _axis_x_value=axis_x_value,
        _axis_x_time=axis_x_time,
        _axis_y=axis_y,
        _title=title,
        _empty_text=empty_text,
    )
    # Apply current theme colors
    widget.apply_theme(colors)
    return widget


__all__ = ["ReadingChartWidget", "build_reading_chart"]
