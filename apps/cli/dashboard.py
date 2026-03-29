"""Retro sci-fi terminal dashboard for live BLE meter readings.

Inspired by the Nostromo computer from Alien — green phosphor, double-line
box drawing, rolling sparkline, big center reading.

Activated via: fluke stream --device <id> --dashboard
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from fluke_core.models.reading import Reading

if TYPE_CHECKING:
    from argparse import Namespace
    from fluke_app import DeviceManager

# Unicode block characters for sparkline (8 levels)
_BLOCKS = " ▁▂▃▄▅▆▇█"


@dataclass
class DashboardState:
    """Mutable state container for the live dashboard."""

    device_label: str = "UNKNOWN DEVICE"
    profile_label: str = ""
    connection_text: str = "CONNECTING"
    measurement_type: str = "—"
    mode: str = "—"
    status: str = "—"
    main_value: str = "—"
    unit: str = ""
    samples: int = 0
    min_value: float | None = None
    max_value: float | None = None
    sum_value: float = 0.0
    numeric_count: int = 0
    values: deque[float] = field(default_factory=lambda: deque(maxlen=60))

    def update(self, reading: Reading) -> None:
        self.samples += 1
        self.measurement_type = reading.measurement_type.value.upper().replace("_", " ")
        self.mode = (reading.mode or "—").upper()
        self.status = reading.status.value.upper()
        self.unit = reading.unit or ""

        if reading.value is not None:
            self.main_value = f"{reading.value:.4g}"
            self.values.append(reading.value)
            self.numeric_count += 1
            self.sum_value += reading.value
            if self.min_value is None or reading.value < self.min_value:
                self.min_value = reading.value
            if self.max_value is None or reading.value > self.max_value:
                self.max_value = reading.value
        elif reading.display_text:
            self.main_value = reading.display_text
        else:
            self.main_value = "OL"

    @property
    def avg_value(self) -> float | None:
        return self.sum_value / self.numeric_count if self.numeric_count else None


def _sparkline(values: deque[float], width: int = 52) -> str:
    """Build a Unicode sparkline string from a deque of float values."""
    if not values:
        return "·" * width

    # Use the last `width` values
    data = list(values)[-width:]
    lo = min(data)
    hi = max(data)
    span = hi - lo if hi != lo else 1.0

    chars = []
    for v in data:
        idx = int((v - lo) / span * 7.999)
        idx = max(0, min(8, idx))
        chars.append(_BLOCKS[idx])

    # Pad left if fewer values than width
    pad = width - len(chars)
    return ("·" * pad) + "".join(chars)


def _format_stat(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:.4g}"


def render_dashboard(state: DashboardState, width: int = 60) -> str:
    """Render the dashboard as a plain string with ANSI green coloring."""
    inner = width - 4  # inside the box borders

    # ANSI escape codes
    GREEN = "\033[32m"
    BRIGHT = "\033[92m"
    DIM = "\033[2;32m"
    RESET = "\033[0m"
    BOLD = "\033[1;92m"

    def center(text: str, w: int = inner) -> str:
        return text.center(w)

    def pad(text: str, w: int = inner) -> str:
        return text.ljust(w)[:w]

    # Header
    header = f"  {state.device_label}  ──  {state.connection_text}  ──  {state.measurement_type}"

    # Big reading
    reading_display = f">>>  {state.main_value} {state.unit}  <<<"

    # Stats
    min_s = _format_stat(state.min_value)
    max_s = _format_stat(state.max_value)
    avg_s = _format_stat(state.avg_value)
    stats_line = f"  MODE: {state.mode}   STATUS: {state.status}   SAMPLES: {state.samples}"
    minmax_line = f"  MIN: {min_s}   MAX: {max_s}   AVG: {avg_s}"

    # Sparkline
    spark_width = inner - 4  # some padding
    spark = _sparkline(state.values, spark_width)
    range_lo = _format_stat(state.min_value) if state.values else "—"
    range_hi = _format_stat(state.max_value) if state.values else "—"
    range_line = f"  {range_lo} {'─' * (inner - len(range_lo) - len(range_hi) - 4)} {range_hi}"

    top = "╔" + "═" * (width - 2) + "╗"
    mid = "╠" + "═" * (width - 2) + "╣"
    bot = "╚" + "═" * (width - 2) + "╝"
    def row(text: str) -> str:
        return f"║ {pad(text)} ║"

    lines = [
        f"{GREEN}{top}",
        f"{GREEN}{row(header)}",
        f"{GREEN}{mid}",
        f"{GREEN}{row('')}",
        f"{BOLD}║ {center(reading_display)} ║{GREEN}",
        f"{GREEN}{row('')}",
        f"{DIM}{row(stats_line)}",
        f"{DIM}{row(minmax_line)}",
        f"{GREEN}{mid}",
        f"{BRIGHT}{row('  ' + spark)}",
        f"{DIM}{row(range_line)}",
        f"{GREEN}{bot}{RESET}",
    ]
    return "\n".join(lines)


async def run_dashboard(manager: "DeviceManager", args: "Namespace") -> int:
    """Run the retro sci-fi dashboard in the terminal."""
    state = DashboardState()

    def on_reading(reading: Reading) -> None:
        state.update(reading)

    manager.subscribe_readings(on_reading)

    device = await manager.connect(args.device, profile_id=args.profile)
    state.device_label = (device.model_name or device.nickname or device.device_id).upper()
    state.profile_label = device.profile_id or args.profile
    state.connection_text = "CONNECTED"
    await manager.start_stream()

    # Clear screen and hide cursor
    print("\033[2J\033[H\033[?25l", end="", flush=True)

    try:
        finished = asyncio.Event()

        if args.count:
            orig_on_reading = on_reading
            count_holder = [0]
            def counting_reading(reading: Reading) -> None:
                orig_on_reading(reading)
                count_holder[0] += 1
                if count_holder[0] >= args.count:
                    finished.set()
            # Re-subscribe can't easily be done, so we track via state.samples
            pass

        while True:
            # Move cursor to top-left and redraw
            print("\033[H", end="")
            print(render_dashboard(state))
            print("\n  \033[2;32mPress Ctrl+C to stop.\033[0m", end="", flush=True)

            try:
                if args.duration > 0:
                    remaining = args.duration - (state.samples * 0.25)  # approximate
                    if remaining <= 0:
                        break
                if args.count and state.samples >= args.count:
                    break
                await asyncio.sleep(0.25)
            except asyncio.CancelledError:
                break
    except KeyboardInterrupt:
        pass
    finally:
        # Show cursor, reset colors
        print("\033[?25h\033[0m")
        await manager.disconnect()

    return 0
