"""异步令牌桶限速，约束元数据源的请求速率。"""
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
