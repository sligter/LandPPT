"""
Simple rate limiter with Valkey (optional) + in-process fallback.

This is used for lightweight protection endpoints such as registration code sending.
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, Optional, Tuple

from ..services.cache_service import get_cache_service

_lock = asyncio.Lock()
_memory_buckets: Dict[str, Tuple[int, float]] = {}


async def hit(key: str, limit: int, window_seconds: int) -> Tuple[bool, int, Optional[int]]:
    """
    Increment a rate-limit bucket.

    Returns (allowed, remaining, reset_in_seconds).
    reset_in_seconds is best-effort (None when unknown).
    """
    cache = await get_cache_service()
    if getattr(cache, "_connected", False):
        value = await cache.incr_with_ttl(key, window_seconds)
        if value is None:
            # fall through to memory
            pass
        else:
            allowed = value <= limit
            remaining = max(0, limit - value)
            return allowed, remaining, None

    now = time.time()
    async with _lock:
        current, reset_at = _memory_buckets.get(key, (0, now + window_seconds))
        if now >= reset_at:
            current, reset_at = 0, now + window_seconds
        current += 1
        _memory_buckets[key] = (current, reset_at)

        allowed = current <= limit
        remaining = max(0, limit - current)
        reset_in = max(0, int(reset_at - now))
        return allowed, remaining, reset_in

