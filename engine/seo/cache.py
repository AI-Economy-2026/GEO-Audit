"""Simple in-process TTL cache for expensive provider calls."""

from __future__ import annotations

import time
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_STORE: dict[str, tuple[float, Any]] = {}


def cached(key: str, ttl_seconds: float, factory: Callable[[], T]) -> T:
    now = time.time()
    hit = _STORE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    value = factory()
    _STORE[key] = (now + ttl_seconds, value)
    return value


def clear_cache() -> None:
    _STORE.clear()
