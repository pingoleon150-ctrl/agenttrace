"""Adaptive per-source rate governing for discovery campaigns.

When a source (github-code, grep, reddit, ...) starts returning bursts of
429/408 responses, the governor progressively increases the delay imposed on
each request to that source. On successful (HTTP 200) responses the penalty
decays geometrically back toward the base delay.
"""
from __future__ import annotations

import asyncio
import re
import time

_HTTP_PENALTY_RE = re.compile(r"\b(429|408|403)\b")
# 403 included because GitHub secondary rate limits often surface as 403.


class RateGovernor:
    def __init__(
        self,
        base_delay: float = 0.0,
        penalty: float = 5.0,
        max_delay: float = 120.0,
        decay: float = 0.5,
        burst_threshold: int = 2,
        lock: asyncio.Lock | None = None,
    ) -> None:
        self.base_delay = base_delay
        self.penalty = penalty
        self.max_delay = max_delay
        self.decay = decay
        self.burst_threshold = burst_threshold
        self._lock = lock or asyncio.Lock()
        self._delays: dict[str, float] = {}
        self._failures: dict[str, int] = {}

    def state(self) -> dict[str, dict[str, float | int]]:
        return {
            source: {"delay_s": round(delay, 2), "failures": self._failures.get(source, 0)}
            for source, delay in self._delays.items()
        }

    async def acquire(self, source: str) -> None:
        """Wait before issuing a request to ``source`` (throttled when penalized)."""
        while True:
            async with self._lock:
                delay = self._delays.get(source, self.base_delay)
            if delay <= 0:
                return
            await asyncio.sleep(delay)
            # loop re-reads in case another task recorded successes meanwhile

    async def record(self, source: str, error: str | None) -> None:
        """Record a job outcome; ``error`` is the campaign error string or None."""
        async with self._lock:
            failures = self._failures.get(source, 0)
            current = self._delays.get(source, self.base_delay)
            if error and _HTTP_PENALTY_RE.search(error):
                failures += 1
                if failures >= self.burst_threshold:
                    steps = failures - self.burst_threshold + 1
                    delay = min(self.max_delay, self.penalty * (2 ** (steps - 1)))
                else:
                    delay = max(current, self.base_delay)
            else:
                failures = 0
                delay = max(self.base_delay, current * self.decay)
            self._failures[source] = failures
            self._delays[source] = delay


# Module-level instance so penalty persists across watch cycles in one process.
GOVERNOR = RateGovernor()


class _GovernorClock:
    """Monotonic clock shim for tests."""

    now = staticmethod(time.monotonic)
