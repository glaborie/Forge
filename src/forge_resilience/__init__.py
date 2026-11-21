"""Circuit breaker for outbound model calls.

Protects a service's own provider calls, and deliberately not the harness: a dead
target is a result there, so suppressing requests would erase the finding.

`failure_threshold` counts consecutive failures. Once open, calls are refused for
`reset_timeout` seconds, then one trial is allowed; success closes the breaker and
failure reopens it with a fresh timer. A `fallback` callable covers both cases the
AC names — another model, or a canned safe response.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


class CircuitOpen(RuntimeError):
    """The breaker refused the call and no fallback was configured."""


@dataclass
class CircuitBreaker:
    failure_threshold: int = 5
    reset_timeout: float = 30.0
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = field(default=None)

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "open" if self.clock() - self.opened_at < self.reset_timeout else "half-open"

    def call(self, func: Callable[[], T], *, fallback: Callable[[], T] | None = None) -> T:
        if self.state == "open":
            if fallback is None:
                raise CircuitOpen(
                    f"circuit open after {self.failures} failure(s); "
                    f"retry in {self.reset_timeout - (self.clock() - (self.opened_at or 0)):.1f}s"
                )
            return fallback()
        try:
            result = func()
        except Exception:
            self._fail()
            if fallback is None:
                raise
            return fallback()
        self._succeed()
        return result

    def _succeed(self) -> None:
        self.failures = 0
        self.opened_at = None

    def _fail(self) -> None:
        self.failures += 1
        if self.opened_at is not None:
            # A failed trial reopens the breaker and restarts the cool-down.
            self.opened_at = self.clock()
        elif self.failures >= self.failure_threshold:
            self.opened_at = self.clock()
