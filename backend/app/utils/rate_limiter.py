import time
import threading


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, rate: float = 1.0):
        """
        Args:
            rate: Minimum seconds between requests.
        """
        self._rate = rate
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until rate limit allows the next request."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < self._rate:
                time.sleep(self._rate - elapsed)
            self._last_request = time.monotonic()
