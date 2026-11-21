from __future__ import annotations

import pytest

from forge_resilience import CircuitBreaker, CircuitOpen


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def failing() -> str:
    raise RuntimeError("provider down")


def working() -> str:
    return "ok"


def test_the_breaker_opens_at_the_threshold() -> None:
    breaker = CircuitBreaker(failure_threshold=2, clock=Clock())

    for _ in range(2):
        with pytest.raises(RuntimeError):
            breaker.call(failing)

    assert breaker.state == "open"


def test_an_open_breaker_refuses_without_calling_the_function() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, clock=clock)
    with pytest.raises(RuntimeError):
        breaker.call(failing)

    calls: list[str] = []

    with pytest.raises(CircuitOpen) as caught:
        breaker.call(lambda: calls.append("called"))

    assert calls == []
    assert "circuit open" in str(caught.value)


def test_a_fallback_is_used_while_open() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, clock=clock)
    with pytest.raises(RuntimeError):
        breaker.call(failing)

    assert breaker.call(working, fallback=lambda: "safe response") == "safe response"


def test_a_fallback_is_used_when_the_call_fails() -> None:
    breaker = CircuitBreaker(failure_threshold=5, clock=Clock())

    assert breaker.call(failing, fallback=lambda: "safe response") == "safe response"
    assert breaker.state == "closed"
    assert breaker.failures == 1


def test_one_trial_is_allowed_after_the_reset_timeout() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=30, clock=clock)
    with pytest.raises(RuntimeError):
        breaker.call(failing)

    clock.advance(30)
    assert breaker.state == "half-open"
    assert breaker.call(working) == "ok"
    assert breaker.state == "closed"
    assert breaker.failures == 0


def test_a_failed_trial_reopens_and_restarts_the_timer() -> None:
    clock = Clock()
    breaker = CircuitBreaker(failure_threshold=1, reset_timeout=30, clock=clock)
    with pytest.raises(RuntimeError):
        breaker.call(failing)

    clock.advance(31)
    assert breaker.state == "half-open"
    with pytest.raises(RuntimeError):
        breaker.call(failing)
    assert breaker.state == "open"

    clock.advance(29)
    assert breaker.state == "open"
    clock.advance(2)
    assert breaker.state == "half-open"


def test_a_success_before_the_threshold_resets_the_count() -> None:
    breaker = CircuitBreaker(failure_threshold=3, clock=Clock())

    with pytest.raises(RuntimeError):
        breaker.call(failing)
    with pytest.raises(RuntimeError):
        breaker.call(failing)
    assert breaker.failures == 2

    breaker.call(working)

    assert breaker.failures == 0
    assert breaker.state == "closed"
