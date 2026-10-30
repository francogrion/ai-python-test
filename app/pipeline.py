"""Background processing in two stages, because their limits are opposite.

Extraction is slow but unlimited, so it gets many workers. Delivery is fast but
rate limited, so it gets a few that share one limiter. The stages are separated
by a queue, so a backlog of notifications never holds back extraction.
"""

import asyncio
import logging
from collections import Counter

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential_jitter

from config import Settings
from guardrails import Accepted, check_input, extract_notification
from models import Notification, RequestRecord, Status
from prompts import build_messages
from provider import AIUnavailable, DeliveryFailed, DeliveryRetryable, ProviderClient
from rate_limiter import RateLimiter
from store import InMemoryStore

logger = logging.getLogger("pipeline")


class Pipeline:
    def __init__(
        self,
        store: InMemoryStore,
        provider: ProviderClient,
        limiter: RateLimiter,
        settings: Settings,
    ) -> None:
        self._store = store
        self._provider = provider
        self._limiter = limiter
        self._settings = settings
        self._extraction_queue: asyncio.Queue[RequestRecord] = asyncio.Queue(maxsize=settings.queue_max_size)
        # Unbounded on purpose: every entry already passed the bounded queue,
        # and extraction outruns delivery by design.
        self._notification_queue: asyncio.Queue[RequestRecord] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._ai_calls = 0
        self._repairs: Counter[str] = Counter()
        self._failures: Counter[str] = Counter()

    async def start(self) -> None:
        self._workers = [
            *(asyncio.create_task(self._run_extraction()) for _ in range(self._settings.extraction_workers)),
            *(asyncio.create_task(self._run_delivery()) for _ in range(self._settings.notification_workers)),
        ]

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers = []

    async def join(self) -> None:
        await self._extraction_queue.join()
        await self._notification_queue.join()

    def submit(self, record: RequestRecord) -> None:
        """Queue a request once. A full queue fails it rather than the HTTP call."""
        if record.submitted:
            return
        record.submitted = True
        try:
            self._extraction_queue.put_nowait(record)
        except asyncio.QueueFull:
            self._fail(record, "overloaded")

    def metrics(self) -> dict:
        return {
            "ai_calls": self._ai_calls,
            "repairs": dict(self._repairs),
            "failures": dict(self._failures),
            "queues": {
                "extraction": self._extraction_queue.qsize(),
                "notification": self._notification_queue.qsize(),
            },
        }

    async def _run_extraction(self) -> None:
        while True:
            record = await self._extraction_queue.get()
            try:
                record.status = Status.PROCESSING
                record.notification = await self._extract(record)
                if record.notification is not None:
                    self._notification_queue.put_nowait(record)
            except Exception:
                logger.exception("id=%s unexpected extraction error", record.id)
                self._fail(record, "internal_error")
            finally:
                self._extraction_queue.task_done()

    async def _run_delivery(self) -> None:
        while True:
            record = await self._notification_queue.get()
            try:
                await self._deliver(record)
            except Exception:
                logger.exception("id=%s unexpected delivery error", record.id)
                self._fail(record, "internal_error")
            finally:
                self._notification_queue.task_done()

    async def _extract(self, record: RequestRecord) -> Notification | None:
        rejection = check_input(record.user_input)
        if rejection is not None:
            self._fail(record, rejection.reason)
            return None

        reason = "ai_unavailable"
        retry_reason = None
        for call in range(1, self._settings.ai_max_calls + 1):
            try:
                self._ai_calls += 1
                content = await self._provider.extract(build_messages(record.user_input, retry_reason))
            except AIUnavailable as error:
                logger.warning("id=%s ai call %d failed: %s", record.id, call, error)
                reason = "ai_unavailable"
                if call < self._settings.ai_max_calls:
                    await asyncio.sleep(self._settings.ai_retry_delay)
                continue

            result = extract_notification(content, record.user_input)
            if isinstance(result, Accepted):
                self._repairs.update(result.repairs)
                return result.notification

            reason = retry_reason = result.reason
            if not result.retryable:
                break

        self._fail(record, reason)
        return None

    async def _deliver(self, record: RequestRecord) -> None:
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._settings.notify_max_attempts),
            wait=wait_exponential_jitter(
                initial=self._settings.notify_retry_base_delay,
                max=self._settings.notify_retry_max_delay,
                jitter=self._settings.notify_retry_base_delay,
            ),
            retry=retry_if_exception_type(DeliveryRetryable),
            reraise=True,
        )
        try:
            async for attempt in retrying:
                with attempt:
                    record.provider_id = await self._send(record)
        except DeliveryRetryable:
            self._fail(record, "delivery_exhausted")
        except DeliveryFailed as error:
            self._fail(record, error.reason)
        else:
            record.status = Status.SENT
            logger.info("id=%s sent", record.id)

    async def _send(self, record: RequestRecord) -> str | None:
        await self._limiter.acquire()
        try:
            return await self._provider.notify(record.notification, trace_id=record.id)
        except DeliveryRetryable as error:
            if error.rate_limited:
                self._limiter.pause(error.retry_after or self._settings.rate_limit_pause)
            raise

    def _fail(self, record: RequestRecord, reason: str) -> None:
        record.status = Status.FAILED
        record.failure_reason = reason
        self._failures[reason] += 1
        logger.info("id=%s failed reason=%s", record.id, reason)
