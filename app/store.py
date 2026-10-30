"""In-memory requests. One event loop, so no locks are needed."""

from uuid import uuid4

from models import RequestRecord, Status


class InMemoryStore:
    def __init__(self) -> None:
        self._records: dict[str, RequestRecord] = {}

    def create(self, user_input: str) -> RequestRecord:
        record = RequestRecord(id=uuid4().hex, user_input=user_input)
        self._records[record.id] = record
        return record

    def get(self, request_id: str) -> RequestRecord | None:
        return self._records.get(request_id)

    def counts(self) -> dict[str, int]:
        counts = {status.value: 0 for status in Status}
        for record in self._records.values():
            counts[record.status.value] += 1
        return counts
