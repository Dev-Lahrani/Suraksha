"""Small in-process sliding-window rate limiter (single-worker deployment)."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from suraksha.config import get_settings

_WINDOW = 60.0
_hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_MAX_KEYS = 10_000


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def rate_limited(bucket: str):
    """FastAPI dependency factory: N requests/minute per client IP per bucket."""

    def dependency(request: Request) -> None:
        limit = get_settings().rate_limit_per_minute
        if limit <= 0:
            return
        now = time.monotonic()
        if len(_hits) > _MAX_KEYS:
            _hits.clear()
        hits = _hits[(bucket, client_ip(request))]
        while hits and now - hits[0] > _WINDOW:
            hits.popleft()
        if len(hits) >= limit:
            raise HTTPException(429, "Too many requests; slow down", headers={"Retry-After": "30"})
        hits.append(now)

    return dependency


def reset() -> None:
    _hits.clear()
