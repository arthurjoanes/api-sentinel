import math
import time
from collections import OrderedDict
from threading import Lock


class RateLimit:
    """Bound request work per network peer without trusting forwarded headers."""

    def __init__(self, rate: float, burst: int, max_keys: int = 1024) -> None:
        self.rate = rate
        self.burst = burst
        self.max_keys = max_keys
        self.buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()
        self.lock = Lock()

    def consume(self, key: str) -> int:
        with self.lock:
            now = time.monotonic()
            if key not in self.buckets and len(self.buckets) >= self.max_keys:
                # Unknown peers share the overflow bucket instead of resetting old budgets.
                key = "overflow"
            balance, updated = self.buckets.get(key, (float(self.burst), now))
            balance = min(float(self.burst), balance + max(0, now - updated) * self.rate)
            retry = 0 if balance >= 1 else max(1, math.ceil((1 - balance) / self.rate))
            self.buckets[key] = (balance - 1 if not retry else balance, now)
            return retry
