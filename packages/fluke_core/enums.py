from __future__ import annotations

from enum import Enum


class MeasurementType(str, Enum):
    VOLTAGE_AC = "voltage_ac"
    VOLTAGE_DC = "voltage_dc"
    CURRENT_AC = "current_ac"
    CURRENT_DC = "current_dc"
    CURRENT_AC_DC = "current_ac_dc"
    CURRENT_INRUSH = "current_inrush"
    RESISTANCE = "resistance"
    CONTINUITY = "continuity"
    CAPACITANCE = "capacitance"
    FREQUENCY = "frequency"
    DUTY_CYCLE = "duty_cycle"
    TEMPERATURE = "temperature"
    UNKNOWN = "unknown"


class ReadingStatus(str, Enum):
    OK = "ok"
    OVER_RANGE = "over_range"
    UNDER_RANGE = "under_range"
    INVALID = "invalid"
    UNSTABLE = "unstable"
    HOLD = "hold"
    NO_SIGNAL = "no_signal"


class ConnectionState(str, Enum):
    IDLE = "idle"
    SCANNING = "scanning"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    STREAMING = "streaming"
    RECONNECTING = "reconnecting"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class WorkflowRunResult(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"


class WorkflowStepResultStatus(str, Enum):
    COMPLETED = "completed"
    CAPTURED = "captured"
    SKIPPED = "skipped"
