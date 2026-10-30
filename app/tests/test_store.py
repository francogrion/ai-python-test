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


def test_the_oldest_finished_requests_are_forgotten_past_the_limit():
    store = InMemoryStore(max_finished=2)
    first, second, third = store.create("a"), store.create("b"), store.create("c")
    store.finish(first)
    store.finish(second)
    store.finish(third)

    assert store.get(first.id) is None
    assert store.get(second.id) is second
    assert store.get(third.id) is third


def test_requests_in_progress_are_never_forgotten():
    store = InMemoryStore(max_finished=1)
    pending = store.create("a")
    store.finish(store.create("b"))
    store.finish(store.create("c"))

    assert store.get(pending.id) is pending


def test_counts_group_requests_by_status():
    store = InMemoryStore()
    store.create("a")
    store.create("b").status = Status.SENT
    assert store.counts() == {"queued": 1, "processing": 0, "sent": 1, "failed": 0}
