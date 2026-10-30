import asyncio

import pytest

from config import Settings
from models import Status
from pipeline import Pipeline
from provider import AIUnavailable, DeliveryFailed, DeliveryRetryable
from store import InMemoryStore

USER_INPUT = "Manda un correo a marta@app.com: Tienes un nuevo mensaje."
GOOD_ANSWER = '{"to": "marta@app.com", "message": "tienes un nuevo mensaje.", "type": "email"}'
REFUSAL = "Lo siento, como IA no tengo permitido procesar datos."


class FakeProvider:
    def __init__(self, answers=None, deliveries=None):
        self.answers = list(answers or [])
        self.deliveries = list(deliveries or [])
        self.ai_calls = []
        self.notify_calls = []

    async def extract(self, messages):
        self.ai_calls.append(messages)
        answer = self.answers.pop(0) if self.answers else GOOD_ANSWER
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def notify(self, notification, trace_id):
        self.notify_calls.append((notification, trace_id))
        outcome = self.deliveries.pop(0) if self.deliveries else "p-1"
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeLimiter:
    def __init__(self):
        self.acquired = 0
        self.pauses = []

    async def acquire(self):
        self.acquired += 1

    def pause(self, seconds):
        self.pauses.append(seconds)


FAST = Settings(
    extraction_workers=2,
    notification_workers=2,
    ai_retry_delay=0,
    notify_retry_base_delay=0,
    notify_retry_max_delay=0,
    notify_max_attempts=3,
)


class Harness:
    def __init__(self, provider, settings=FAST):
        self.store = InMemoryStore()
        self.provider = provider
        self.limiter = FakeLimiter()
        self.pipeline = Pipeline(self.store, provider, self.limiter, settings)

    async def run(self, user_input=USER_INPUT):
        record = self.store.create(user_input)
        self.pipeline.submit(record)
        await self.pipeline.join()
        return record


@pytest.fixture
async def harness():
    created = []

    async def build(provider=None, settings=FAST):
        instance = Harness(provider or FakeProvider(), settings)
        await instance.pipeline.start()
        created.append(instance)
        return instance

    yield build

    for instance in created:
        await instance.pipeline.stop()


async def test_a_clean_request_ends_sent(harness):
    h = await harness()
    record = await h.run()

    assert record.status is Status.SENT
    assert record.provider_id == "p-1"
    assert record.failure_reason is None
    assert len(h.provider.ai_calls) == 1


async def test_the_validated_notification_is_what_gets_sent_with_a_stable_trace_id(harness):
    h = await harness()
    record = await h.run()

    notification, trace_id = h.provider.notify_calls[0]
    assert notification.message == "Tienes un nuevo mensaje."
    assert trace_id == record.id


async def test_a_repairable_answer_needs_no_second_call(harness):
    h = await harness(FakeProvider(["{'to': 'marta@app.com', 'message': 'x'}"]))
    record = await h.run()

    assert record.status is Status.SENT
    assert len(h.provider.ai_calls) == 1
    assert h.pipeline.metrics()["repairs"]["json_repaired"] == 1


async def test_a_refusal_is_asked_again_once_with_a_hint(harness):
    h = await harness(FakeProvider([REFUSAL]))
    record = await h.run()

    assert record.status is Status.SENT
    first, second = h.provider.ai_calls
    assert second[0]["content"] != first[0]["content"]
    assert second[1:] == first[1:]


async def test_the_ai_budget_is_two_calls(harness):
    h = await harness(FakeProvider([REFUSAL, REFUSAL, GOOD_ANSWER]))
    record = await h.run()

    assert record.status is Status.FAILED
    assert record.failure_reason == "no_json"
    assert len(h.provider.ai_calls) == 2


async def test_a_request_without_recipient_never_reaches_the_ai(harness):
    h = await harness()
    record = await h.run("Avisa a Pedro: hola")

    assert record.status is Status.FAILED
    assert record.failure_reason == "no_recipient"
    assert h.provider.ai_calls == []


async def test_a_final_rejection_is_not_asked_again(harness):
    answer = '{"to": "ana@test.com", "message": "mail a ana@test.com nos vemos", "type": "email"}'
    h = await harness(FakeProvider([answer]))
    record = await h.run("Mail a ana@test.com nos vemos")

    assert record.failure_reason == "message_unverified"
    assert len(h.provider.ai_calls) == 1
    assert h.provider.notify_calls == []


async def test_an_ai_outage_is_tried_again_within_the_budget(harness):
    h = await harness(FakeProvider([AIUnavailable("down")]))
    record = await h.run()

    assert record.status is Status.SENT
    assert len(h.provider.ai_calls) == 2


async def test_a_persistent_ai_outage_fails_the_request(harness):
    h = await harness(FakeProvider([AIUnavailable("down"), AIUnavailable("down")]))
    record = await h.run()

    assert record.failure_reason == "ai_unavailable"
    assert len(h.provider.ai_calls) == 2


async def test_every_send_attempt_goes_through_the_limiter(harness):
    h = await harness(FakeProvider(deliveries=[DeliveryRetryable(), "p-2"]))
    record = await h.run()

    assert record.status is Status.SENT
    assert record.provider_id == "p-2"
    assert h.limiter.acquired == 2


async def test_a_429_pauses_all_sends_for_retry_after(harness):
    h = await harness(FakeProvider(deliveries=[DeliveryRetryable(rate_limited=True, retry_after=7), "p-2"]))
    await h.run()

    assert h.limiter.pauses == [7]


async def test_a_429_without_retry_after_uses_the_default_pause(harness):
    h = await harness(FakeProvider(deliveries=[DeliveryRetryable(rate_limited=True), "p-2"]))
    await h.run()

    assert h.limiter.pauses == [FAST.rate_limit_pause]


async def test_retrying_delivery_does_not_repeat_the_extraction(harness):
    h = await harness(FakeProvider(deliveries=[DeliveryRetryable(), DeliveryRetryable(), "p-2"]))
    await h.run()

    assert len(h.provider.ai_calls) == 1


async def test_delivery_gives_up_after_its_attempts(harness):
    h = await harness(FakeProvider(deliveries=[DeliveryRetryable() for _ in range(5)]))
    record = await h.run()

    assert record.status is Status.FAILED
    assert record.failure_reason == "delivery_exhausted"
    assert len(h.provider.notify_calls) == FAST.notify_max_attempts


async def test_a_final_delivery_failure_is_not_retried(harness):
    h = await harness(FakeProvider(deliveries=[DeliveryFailed("delivery_unknown")]))
    record = await h.run()

    assert record.failure_reason == "delivery_unknown"
    assert len(h.provider.notify_calls) == 1


async def test_submitting_twice_processes_once(harness):
    h = await harness()
    record = h.store.create(USER_INPUT)
    h.pipeline.submit(record)
    h.pipeline.submit(record)
    await h.pipeline.join()

    assert len(h.provider.ai_calls) == 1
    assert len(h.provider.notify_calls) == 1


async def test_a_finished_request_is_not_sent_again(harness):
    h = await harness()
    record = await h.run()
    h.pipeline.submit(record)
    await h.pipeline.join()

    assert len(h.provider.notify_calls) == 1


async def test_an_unexpected_error_fails_that_request_and_the_workers_survive(harness):
    h = await harness(FakeProvider([RuntimeError("boom"), RuntimeError("boom")], [RuntimeError("boom")]))
    first = await h.run()
    second = await h.run()
    third = await h.run()

    assert [first.failure_reason, second.failure_reason] == ["internal_error", "internal_error"]
    assert third.failure_reason == "internal_error"
    assert (await h.run()).status is Status.SENT


async def test_a_full_queue_fails_the_request_instead_of_raising():
    h = Harness(FakeProvider(), Settings(queue_max_size=1))
    first = h.store.create(USER_INPUT)
    second = h.store.create(USER_INPUT)

    h.pipeline.submit(first)
    h.pipeline.submit(second)

    assert first.status is Status.QUEUED
    assert second.status is Status.FAILED
    assert second.failure_reason == "overloaded"


async def test_status_is_processing_while_the_ai_works(harness):
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowProvider(FakeProvider):
        async def extract(self, messages):
            started.set()
            await release.wait()
            return await super().extract(messages)

    h = await harness(SlowProvider())
    record = h.store.create(USER_INPUT)
    h.pipeline.submit(record)
    assert record.status is Status.QUEUED

    await started.wait()
    assert record.status is Status.PROCESSING

    release.set()
    await h.pipeline.join()
    assert record.status is Status.SENT


async def test_a_blocked_delivery_does_not_hold_back_extraction(harness):
    release = asyncio.Event()

    class BlockedDelivery(FakeProvider):
        async def notify(self, notification, trace_id):
            await release.wait()
            return await super().notify(notification, trace_id)

    settings = Settings(extraction_workers=1, notification_workers=1, ai_retry_delay=0)
    h = await harness(BlockedDelivery(), settings)
    for _ in range(3):
        h.pipeline.submit(h.store.create(USER_INPUT))

    await asyncio.wait_for(_until(lambda: len(h.provider.ai_calls) == 3), timeout=1)

    release.set()
    await h.pipeline.join()
    assert h.store.counts()["sent"] == 3


async def test_metrics_report_calls_and_failures(harness):
    h = await harness(FakeProvider([REFUSAL, REFUSAL]))
    await h.run()
    await h.run("Avisa a Pedro: hola")

    metrics = h.pipeline.metrics()
    assert metrics["ai_calls"] == 2
    assert metrics["failures"] == {"no_json": 1, "no_recipient": 1}
    assert metrics["queues"] == {"extraction": 0, "notification": 0}


async def _until(condition):
    while not condition():
        await asyncio.sleep(0)
