"""In-process sliding-window rate limiter.

Adequate for a single instance; a multi-instance deployment would back this with Redis.
"""

import math
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, status

from app.core.config import get_settings


class RateLimiter:
    def __init__(self, name: str, limit: int, window_seconds: float = 60.0) -> None:
        self.name = name
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str) -> None:
        if not get_settings().rate_limit_enabled:
            return
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = math.ceil(hits[0] + self.window - now)
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"Too many {self.name} requests; retry in {retry_after}s",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


_settings = get_settings()
register_limiter = RateLimiter("registration", _settings.rate_limit_register_per_minute)
login_limiter = RateLimiter("login", _settings.rate_limit_login_per_minute)
upload_limiter = RateLimiter("upload", _settings.rate_limit_upload_per_minute)
ALL_LIMITERS = (register_limiter, login_limiter, upload_limiter)
