# a2a_server/middleware/rate_limit.py
from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Deque, Dict

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

__all__ = ["RateLimiterMiddleware"]


class RateLimiterMiddleware(BaseHTTPMiddleware):
    """Token-bucket style limiter (IP route) - 30-req / 60's by default."""

    def __init__(self, app, *, capacity: int = 30, window: int = 60):
        super().__init__(app)
        self.capacity = capacity
        self.window = window
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        key = f"{request.client.host}:{request.url.path}"
        now = time.time()
        bucket = self._buckets[key]

        # drop old timestamps
        cutoff = now - self.window
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

        if len(bucket) >= self.capacity:
            return JSONResponse({"detail": "rate limit"}, status_code=429)

        bucket.append(now)
        return await call_next(request)