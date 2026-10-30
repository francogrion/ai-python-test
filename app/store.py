"""In-memory requests. One event loop, so no locks are needed."""

from collections import deque
from uuid import uuid4

from models import RequestRecord, Status


class InMemoryStore:
    def __init__(self, max_finished: int = 100_000) -> None:
        self._records: dict[str, RequestRecord] = {}
        self._max_finished = max_finished
        self._finished: deque[str] = deque()

    def create(self, user_input: str) -> RequestRecord:
        record = RequestRecord(id=uuid4().hex, user_input=user_input)
        self._records[record.id] = record
        return record

    def get(self, request_id: str) -> RequestRecord | None:
        return self._records.get(request_id)

    def finish(self, record: RequestRecord) -> None:
        """Remember a finished request, forgetting the oldest ones past the limit."""
        self._finished.append(record.id)
        while len(self._finished) > self._max_finished:
            self._records.pop(self._finished.popleft(), None)

    def finished(self) -> list[str]:
        return list(self._finished)

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for record in self._records.values():
            counts[record.status.value] += 1
        return counts
