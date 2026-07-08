from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ReconnectPolicy:
    """Configurable exponential-backoff-with-jitter policy for automatic reconnects.

    This collaborator is intentionally pure and side-effect free so it can be unit
    tested without any BLE stack or event loop. ``DeviceManager`` owns an instance
    and consults it while recovering from an *unexpected* connection drop.

    Attributes:
        enabled: master switch. When ``False`` no automatic reconnect is attempted.
        initial_delay_s: delay before the first retry (attempt 1).
        max_delay_s: upper bound applied to every computed backoff delay.
        multiplier: growth factor applied per attempt (2.0 == doubling).
        jitter: fractional +/- jitter applied to each delay (0..1). ``0.25`` means
            the returned delay is uniformly sampled within +/-25% of the base delay.
        max_attempts: maximum number of reconnect attempts. ``0`` means unlimited
            (bounded only by ``give_up_after_s`` if that is set).
        give_up_after_s: overall wall-clock budget for a single recovery episode.
            ``0`` means no overall timeout (bounded only by ``max_attempts``).
    """

    enabled: bool = True
    initial_delay_s: float = 0.5
    max_delay_s: float = 30.0
    multiplier: float = 2.0
    jitter: float = 0.25
    max_attempts: int = 0
    give_up_after_s: float = 0.0

    def base_delay(self, attempt: int) -> float:
        """Return the un-jittered backoff delay for a 1-based ``attempt`` number."""
        step = max(1, int(attempt))
        raw = float(self.initial_delay_s) * (float(self.multiplier) ** (step - 1))
        return max(0.0, min(raw, float(self.max_delay_s)))

    def delay_for(self, attempt: int, *, rng: Callable[[], float] | None = None) -> float:
        """Return the jittered backoff delay (seconds) before ``attempt``.

        ``rng`` returns a float in ``[0, 1)`` (defaults to ``random.random``) and is
        injectable so tests can make the result deterministic.
        """
        base = self.base_delay(attempt)
        jitter = max(0.0, min(1.0, float(self.jitter)))
        if jitter <= 0.0 or base <= 0.0:
            return base
        sample = (rng or random.random)()
        offset = base * jitter * (2.0 * sample - 1.0)
        return max(0.0, base + offset)

    def has_attempts_remaining(self, next_attempt: int) -> bool:
        """Whether a reconnect attempt numbered ``next_attempt`` (1-based) is allowed."""
        if self.max_attempts <= 0:
            return True
        return int(next_attempt) <= int(self.max_attempts)

    def has_time_remaining(self, elapsed_s: float) -> bool:
        """Whether the overall give-up budget still permits another attempt."""
        if self.give_up_after_s <= 0:
            return True
        return float(elapsed_s) < float(self.give_up_after_s)

    def should_attempt(self, next_attempt: int, elapsed_s: float) -> bool:
        """Combined gate: enabled, attempts left, and time left."""
        return (
            self.enabled
            and self.has_attempts_remaining(next_attempt)
            and self.has_time_remaining(elapsed_s)
        )

    def describe(self) -> str:
        attempts = "unlimited" if self.max_attempts <= 0 else str(self.max_attempts)
        budget = "no timeout" if self.give_up_after_s <= 0 else f"{self.give_up_after_s:g}s"
        return (
            f"exp backoff initial={self.initial_delay_s:g}s max={self.max_delay_s:g}s "
            f"x{self.multiplier:g} jitter={self.jitter:g} attempts={attempts} budget={budget}"
        )
