import random
import time
import threading


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, rate: float = 1.0, jitter: float = 0.0):
        """
        Args:
            rate: Minimum seconds between requests.
            jitter: Fraction of ``rate`` to randomize each wait by
                (e.g. 0.4 → effective spacing in [0.6·rate, 1.4·rate]).
                A robotic fixed cadence is a bot-detection signal;
                jitter makes the request rhythm look organic.
        """
        self._rate = rate
        self._jitter = max(0.0, jitter)
        self._last_request = 0.0
        self._lock = threading.Lock()

    def wait(self) -> None:
        """Block until rate limit allows the next request."""
        with self._lock:
            spacing = self._rate
            if self._jitter:
                spacing *= 1.0 + random.uniform(-self._jitter, self._jitter)
            now = time.monotonic()
            elapsed = now - self._last_request
            if elapsed < spacing:
                time.sleep(spacing - elapsed)
            self._last_request = time.monotonic()
