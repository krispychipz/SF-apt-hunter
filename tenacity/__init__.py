"""Simple tenacity substitute for retries."""
from __future__ import annotations

import time
from typing import Any, Callable


class RetryError(Exception):
    pass


def stop_after_attempt(attempts: int) -> int:
    return attempts


def wait_exponential(multiplier: float = 1.0, min: float = 0.0, max: float | None = None):
    return {
        "multiplier": multiplier,
        "min": min,
        "max": max,
    }


def retry(*, stop: int, wait: dict[str, float | None]):
    def decorator(fn: Callable):
        def wrapper(*args, **kwargs):
            attempts = 0
            last_exc: Exception | None = None
            while attempts < stop:
                try:
                    return fn(*args, **kwargs)
                except Exception as exc:  # pragma: no cover - network errors
                    last_exc = exc
                    attempts += 1
                    if attempts >= stop:
                        raise RetryError(exc) from exc
                    delay = wait.get("multiplier", 1.0) * (2 ** (attempts - 1))
                    delay = max(delay, wait.get("min", 0.0) or 0.0)
                    max_delay = wait.get("max")
                    if max_delay is not None:
                        delay = min(delay, max_delay)
                    time.sleep(delay)
            if last_exc:
                raise RetryError(last_exc)
        return wrapper
    return decorator


__all__ = ["retry", "stop_after_attempt", "wait_exponential", "RetryError"]
