import asyncio

import pytest

from rate_limiter import RateLimiter


class VirtualTime:
    def __init__(self):
        self.now = 1000.0
        self.sends = []

    def clock(self):
        return self.now

    async def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def time_source():
    return VirtualTime()


def limiter(time_source, rate=4.5):
    return RateLimiter(rate, clock=time_source.clock, sleep=time_source.sleep)


async def test_first_acquire_does_not_wait(time_source):
    await limiter(time_source).acquire()
    assert time_source.now == 1000.0


async def test_acquires_are_spaced_by_the_rate(time_source):
    bucket = limiter(time_source, rate=2)
    await bucket.acquire()
    await bucket.acquire()
    assert time_source.now == pytest.approx(1000.5)


async def test_idle_time_does_not_build_up_a_burst(time_source):
    bucket = limiter(time_source, rate=2)
    await bucket.acquire()
    time_source.now += 60
    await bucket.acquire()
    start = time_source.now
    await bucket.acquire()
    assert time_source.now == pytest.approx(start + 0.5)


async def test_no_ten_second_window_exceeds_the_provider_limit(time_source):
    bucket = limiter(time_source)
    sends = []
    for _ in range(500):
        await bucket.acquire()
        sends.append(time_source.now)

    for first, start in enumerate(sends):
        in_window = [send for send in sends[first:] if send - start < 10]
        assert len(in_window) <= 46


async def test_concurrent_callers_each_get_their_own_slot():
    bucket = RateLimiter(50)
    loop = asyncio.get_running_loop()
    start = loop.time()
    await asyncio.gather(*(bucket.acquire() for _ in range(5)))
    assert loop.time() - start >= 0.07


async def test_pause_delays_the_next_acquire(time_source):
    bucket = limiter(time_source)
    await bucket.acquire()
    bucket.pause(2)
    await bucket.acquire()
    assert time_source.now == pytest.approx(1002.0)


async def test_a_pause_also_holds_back_a_caller_already_waiting(time_source):
    pauses = []

    async def sleep_and_pause_once(seconds):
        await time_source.sleep(seconds)
        if not pauses:
            pauses.append(seconds)
            bucket.pause(5)

    bucket = RateLimiter(2, clock=time_source.clock, sleep=sleep_and_pause_once)
    await bucket.acquire()
    await bucket.acquire()

    assert time_source.now == pytest.approx(1005.5)


async def test_pause_never_shortens_a_longer_pause(time_source):
    bucket = limiter(time_source)
    bucket.pause(5)
    bucket.pause(1)
    await bucket.acquire()
    assert time_source.now == pytest.approx(1005.0)
