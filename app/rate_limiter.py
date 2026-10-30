"""Client-side pacing for /v1/notify, so the provider never has to answer 429."""

import asyncio
import time
from collections.abc import Awaitable, Callable


class RateLimiter:
    """GCRA: remembers the next allowed send instead of counting tokens.

    With no burst, at most 1 + rate * T calls fit in any window of T seconds,
    so 4.5/s means 46 every 10 s against the provider's limit of 50.
    """

    def __init__(
        self,
        rate_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = 1 / rate_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_slot = 0.0

    async def acquire(self) -> None:
        now = self._clock()
        slot = max(self._next_slot, now)
        self._next_slot = slot + self._interval
        if slot > now:
            await self._sleep(slot - now)

    def pause(self, seconds: float) -> None:
        self._next_slot = max(self._next_slot, self._clock() + seconds)
