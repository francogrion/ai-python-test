from models import Status
from store import InMemoryStore


def test_new_requests_start_queued_with_their_input():
    record = InMemoryStore().create("hola")
    assert record.status is Status.QUEUED
    assert record.user_input == "hola"


def test_ids_are_unique():
    store = InMemoryStore()
    assert store.create("a").id != store.create("b").id


def test_get_returns_the_same_record():
    store = InMemoryStore()
    record = store.create("hola")
    assert store.get(record.id) is record


def test_get_unknown_id_returns_none():
    assert InMemoryStore().get("nope") is None


def test_counts_group_requests_by_status():
    store = InMemoryStore()
    store.create("a")
    store.create("b").status = Status.SENT
    assert store.counts() == {"queued": 1, "processing": 0, "sent": 1, "failed": 0}
