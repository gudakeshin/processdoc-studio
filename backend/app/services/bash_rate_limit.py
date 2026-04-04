"""Simple in-memory rate limiting for bash-capable API (per user)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from app.core.config import settings

_LOCK = Lock()
_EVENTS: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(user_key: str) -> tuple[bool, str]:
    limit = int(settings.bash_rate_limit_per_minute)
    if limit <= 0:
        return True, ""
    window = 60.0
    now = time.time()
    with _LOCK:
        q = _EVENTS[user_key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return False, f"Rate limit exceeded ({limit} requests per minute)."
        q.append(now)
    return True, ""
