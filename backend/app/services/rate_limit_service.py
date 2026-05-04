"""Rate-limit service — E-5.5.

In-memory sliding-window counter. One process = one bucket-set.

For self-host with a single uvicorn worker (which is the supported
configuration on Windows due to Celery's --pool=solo requirement),
in-process state is sufficient. For multi-worker SaaS deployments
the same `check_and_consume` call site can be backed by Redis with
the existing redis dependency; the swap is one function. This module
deliberately stays simple so the in-memory and Redis paths share the
same contract.

Sliding window strategy:
  bucket key = (request_key, current_minute_epoch)
  on each request:
    counter[bucket] += 1
    if counter > limit: return (False, retry_after_sec)
    else: return (True, ...)

Buckets older than ``window_sec`` are pruned on each access; the
prune is O(buckets), which stays small because we only keep at most
``window_sec / 60 + 1`` entries per request_key.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    """A bucket configuration."""

    requests: int
    window_sec: int = 60

    def __post_init__(self) -> None:
        if self.requests <= 0:
            raise ValueError("requests must be > 0")
        if self.window_sec <= 0:
            raise ValueError("window_sec must be > 0")


# {key: {bucket_epoch: count}} — keyed by full namespaced key
# (e.g. "user:abc:login", "ip:1.2.3.4:login", "user:abc:default").
_buckets: dict[str, dict[int, int]] = defaultdict(dict)
_lock = threading.Lock()


def _now() -> int:
    return int(time.time())


def _bucket_epoch(now: int, window_sec: int) -> int:
    """Bucket index = floor(now / window_sec). Each bucket is one
    full window long."""
    return now // window_sec


def check_and_consume(
    key: str,
    limit: RateLimit,
    *,
    now: int | None = None,
) -> tuple[bool, int, int]:
    """Atomically check the bucket and increment if allowed.

    Returns ``(allowed, current_count, retry_after_sec)``:
    - ``allowed=True`` if the call is within the limit; counter has
      been incremented.
    - ``allowed=False`` if the call would exceed the limit; counter
      has NOT been incremented. ``retry_after_sec`` is the number of
      seconds until the bucket rolls over.

    Caller MUST handle the case where Redis (or whatever backend
    swaps in later) is down — the contract is that any failure to
    reach the backend should fail-open, not fail-closed.
    """
    if now is None:
        now = _now()
    epoch = _bucket_epoch(now, limit.window_sec)

    with _lock:
        bucket = _buckets[key]
        # Prune old entries first.
        for old_epoch in list(bucket.keys()):
            if old_epoch < epoch:
                del bucket[old_epoch]

        current = bucket.get(epoch, 0)
        if current >= limit.requests:
            # Compute retry_after as seconds until the next epoch starts.
            next_epoch_start = (epoch + 1) * limit.window_sec
            retry_after = max(1, next_epoch_start - now)
            return False, current, retry_after

        bucket[epoch] = current + 1
        return True, current + 1, 0


def reset(key: str | None = None) -> None:
    """Test helper: reset a single bucket-set or all of them."""
    with _lock:
        if key is None:
            _buckets.clear()
        else:
            _buckets.pop(key, None)


def snapshot() -> dict[str, dict[int, int]]:
    """Test helper: return a copy of all buckets for inspection."""
    with _lock:
        return {k: dict(v) for k, v in _buckets.items()}
