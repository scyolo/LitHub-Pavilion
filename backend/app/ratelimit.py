"""限速原语：令牌桶（RPS）与最小间隔（arXiv 3s/篇）。"""
import asyncio
import time


class AsyncTokenBucket:
    """令牌桶限速器：rate=每秒请求数，capacity=突发容量。"""

    def __init__(self, rate: float, capacity: float = 1.0):
        self.rate = max(rate, 0.01)
        self.capacity = capacity
        self._tokens = capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self.rate)


class MinInterval:
    """最小间隔限速器：两次 acquire 之间至少间隔 interval 秒。"""

    def __init__(self, interval: float):
        self.interval = interval
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._next_at - now
            if wait > 0:
                await asyncio.sleep(wait)
                now = time.monotonic()
            self._next_at = max(now, self._next_at) + self.interval
