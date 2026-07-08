"""Shared threshold / status alert evaluation.

`AlertEvaluator` is a small, hardware-free state machine used by every surface
(CLI ``fluke alert``, the desktop Live Reading tab, and any SDK consumer) so the
alarm semantics stay identical everywhere.

It supports:

- high / low value thresholds
- an out-of-band *duration debounce* so momentary spikes do not fire the alarm
- reading-status alerts (over-range, under-range, no-signal)
- an externally signalled connection-lost alert

The evaluator is deterministic: debounce timing is driven off each
``Reading.timestamp_utc`` (falling back to a wall clock only when a reading
carries no timestamp), which keeps it trivially unit-testable without sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from fluke_core.enums import ReadingStatus
from fluke_core.models.reading import Reading


class AlertKind(str, Enum):
    NONE = "none"
    HIGH = "high"
    LOW = "low"
    STATUS = "status"
    CONNECTION_LOST = "connection_lost"


# Reading statuses that are treated as an alarm condition when status alerts are on.
_ALARM_STATUSES: dict[ReadingStatus, str] = {
    ReadingStatus.OVER_RANGE: "over-range",
    ReadingStatus.UNDER_RANGE: "under-range",
    ReadingStatus.NO_SIGNAL: "no signal",
}


@dataclass(frozen=True, slots=True)
class AlertConfig:
    """User-facing alert configuration.

    ``debounce_seconds`` is the continuous out-of-band duration that must elapse
    before a value threshold alarm fires. ``0`` fires immediately.
    """

    high: float | None = None
    low: float | None = None
    debounce_seconds: float = 0.0
    status_alerts: bool = True
    connection_alerts: bool = True

    @property
    def enabled(self) -> bool:
        return (
            self.high is not None
            or self.low is not None
            or self.status_alerts
            or self.connection_alerts
        )

    def validate(self) -> None:
        if self.high is not None and self.low is not None and self.low >= self.high:
            raise ValueError("low threshold must be less than high threshold.")
        if self.debounce_seconds < 0:
            raise ValueError("debounce_seconds must be non-negative.")


@dataclass(frozen=True, slots=True)
class AlertEvaluation:
    """Result of feeding one reading (or a connection event) to the evaluator."""

    active: bool = False
    kind: AlertKind = AlertKind.NONE
    message: str = ""
    signature: str = ""
    value: float | None = None
    unit: str = ""
    # Rising edge: a *new* alarm episode began on this evaluation.
    just_triggered: bool = False
    # Falling edge: the previous alarm episode cleared on this evaluation.
    just_cleared: bool = False
    # True while the value is out of band but still inside the debounce window.
    pending: bool = False


@dataclass
class AlertEvaluator:
    """Stateful alarm evaluator shared across surfaces."""

    config: AlertConfig = field(default_factory=AlertConfig)
    _out_of_band_since: datetime | None = field(default=None, init=False, repr=False)
    _active_signature: str | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        self.config.validate()

    def set_config(self, config: AlertConfig) -> None:
        config.validate()
        self.config = config
        self.reset()

    def reset(self) -> None:
        self._out_of_band_since = None
        self._active_signature = None

    def evaluate(self, reading: Reading) -> AlertEvaluation:
        """Evaluate a single reading and return the current alarm state."""
        now = reading.timestamp_utc or datetime.now(timezone.utc)

        # Status alerts take priority and are not debounced -- an over-range
        # meter is an immediate, unambiguous condition.
        if self.config.status_alerts and reading.status in _ALARM_STATUSES:
            label = _ALARM_STATUSES[reading.status]
            signature = f"status:{reading.status.value}"
            message = f"STATUS ALERT: meter reports {label}."
            self._out_of_band_since = None
            return self._transition(
                AlertKind.STATUS,
                signature,
                message,
                value=reading.value,
                unit=reading.unit,
            )

        value = reading.value
        breach = self._value_breach(value)
        if breach is None:
            self._out_of_band_since = None
            return self._transition(AlertKind.NONE, None, "", value=value, unit=reading.unit)

        kind, threshold = breach
        if self._out_of_band_since is None:
            self._out_of_band_since = now
        elapsed = (now - self._out_of_band_since).total_seconds()
        if elapsed < self.config.debounce_seconds:
            # Out of band but still inside the debounce window -- not firing yet.
            return AlertEvaluation(
                active=False,
                kind=AlertKind.NONE,
                pending=True,
                value=value,
                unit=reading.unit,
                just_cleared=self._clear_if_active(),
            )

        signature = f"{kind.value}:{threshold}"
        comparator = "exceeds" if kind is AlertKind.HIGH else "below"
        message = (
            f"{kind.value.upper()} ALERT: {value:.4g} {reading.unit} "
            f"{comparator} {threshold:.4g}".replace("  ", " ").strip()
        )
        return self._transition(kind, signature, message, value=value, unit=reading.unit)

    def note_connection_lost(self, detail: str = "") -> AlertEvaluation:
        """Signal that the connection dropped. Returns a connection-lost alert."""
        if not self.config.connection_alerts:
            return AlertEvaluation()
        message = "CONNECTION LOST" + (f": {detail}" if detail else ".")
        return self._transition(
            AlertKind.CONNECTION_LOST,
            "connection_lost",
            message,
        )

    def note_connection_restored(self) -> AlertEvaluation:
        """Clear an active connection-lost alarm."""
        self._out_of_band_since = None
        return self._transition(AlertKind.NONE, None, "")

    def _value_breach(self, value: float | None) -> tuple[AlertKind, float] | None:
        if value is None:
            return None
        if self.config.high is not None and value > self.config.high:
            return AlertKind.HIGH, self.config.high
        if self.config.low is not None and value < self.config.low:
            return AlertKind.LOW, self.config.low
        return None

    def _transition(
        self,
        kind: AlertKind,
        signature: str | None,
        message: str,
        *,
        value: float | None = None,
        unit: str = "",
    ) -> AlertEvaluation:
        active = kind is not AlertKind.NONE
        just_triggered = active and signature != self._active_signature
        just_cleared = not active and self._active_signature is not None
        self._active_signature = signature if active else None
        return AlertEvaluation(
            active=active,
            kind=kind,
            message=message,
            signature=signature or "",
            value=value,
            unit=unit,
            just_triggered=just_triggered,
            just_cleared=just_cleared,
        )

    def _clear_if_active(self) -> bool:
        if self._active_signature is not None:
            self._active_signature = None
            return True
        return False
