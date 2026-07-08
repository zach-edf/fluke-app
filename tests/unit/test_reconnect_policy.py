from __future__ import annotations

import unittest

from fluke_app.reconnect_policy import ReconnectPolicy


class ReconnectPolicyTests(unittest.TestCase):
    def test_base_delay_grows_exponentially(self) -> None:
        policy = ReconnectPolicy(initial_delay_s=0.5, multiplier=2.0, max_delay_s=100.0, jitter=0.0)
        self.assertAlmostEqual(policy.base_delay(1), 0.5)
        self.assertAlmostEqual(policy.base_delay(2), 1.0)
        self.assertAlmostEqual(policy.base_delay(3), 2.0)
        self.assertAlmostEqual(policy.base_delay(4), 4.0)

    def test_base_delay_capped_at_max(self) -> None:
        policy = ReconnectPolicy(initial_delay_s=1.0, multiplier=10.0, max_delay_s=30.0, jitter=0.0)
        self.assertAlmostEqual(policy.base_delay(1), 1.0)
        self.assertAlmostEqual(policy.base_delay(2), 10.0)
        self.assertAlmostEqual(policy.base_delay(3), 30.0)
        self.assertAlmostEqual(policy.base_delay(9), 30.0)

    def test_delay_for_without_jitter_is_deterministic(self) -> None:
        policy = ReconnectPolicy(initial_delay_s=0.5, multiplier=2.0, jitter=0.0)
        self.assertAlmostEqual(policy.delay_for(3), 2.0)

    def test_delay_for_jitter_bounds(self) -> None:
        policy = ReconnectPolicy(initial_delay_s=1.0, multiplier=1.0, jitter=0.25, max_delay_s=100.0)
        base = policy.base_delay(1)  # 1.0
        # rng=0.0 -> lowest edge (base - 25%), rng returns nearly 1.0 -> highest edge (base + 25%).
        low = policy.delay_for(1, rng=lambda: 0.0)
        high = policy.delay_for(1, rng=lambda: 1.0)
        mid = policy.delay_for(1, rng=lambda: 0.5)
        self.assertAlmostEqual(low, base * 0.75)
        self.assertAlmostEqual(high, base * 1.25)
        self.assertAlmostEqual(mid, base)
        # Jitter never yields a negative delay.
        aggressive = ReconnectPolicy(initial_delay_s=0.1, multiplier=1.0, jitter=1.0)
        self.assertGreaterEqual(aggressive.delay_for(1, rng=lambda: 0.0), 0.0)

    def test_attempts_remaining_respects_max_attempts(self) -> None:
        unlimited = ReconnectPolicy(max_attempts=0)
        self.assertTrue(unlimited.has_attempts_remaining(1000))
        limited = ReconnectPolicy(max_attempts=3)
        self.assertTrue(limited.has_attempts_remaining(3))
        self.assertFalse(limited.has_attempts_remaining(4))

    def test_time_remaining_respects_budget(self) -> None:
        unbounded = ReconnectPolicy(give_up_after_s=0.0)
        self.assertTrue(unbounded.has_time_remaining(10_000.0))
        bounded = ReconnectPolicy(give_up_after_s=5.0)
        self.assertTrue(bounded.has_time_remaining(4.9))
        self.assertFalse(bounded.has_time_remaining(5.0))
        self.assertFalse(bounded.has_time_remaining(9.0))

    def test_should_attempt_combines_gates(self) -> None:
        policy = ReconnectPolicy(enabled=True, max_attempts=2, give_up_after_s=5.0)
        self.assertTrue(policy.should_attempt(1, 0.0))
        self.assertFalse(policy.should_attempt(3, 0.0))  # attempt cap
        self.assertFalse(policy.should_attempt(1, 6.0))  # time cap
        disabled = ReconnectPolicy(enabled=False)
        self.assertFalse(disabled.should_attempt(1, 0.0))


if __name__ == "__main__":
    unittest.main()
