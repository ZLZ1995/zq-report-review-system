from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from asset_based_agent.technical_platform.store import PlatformStore


def test_concurrent_claim_has_exactly_one_winner(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    barrier = Barrier(2)

    def claim():
        barrier.wait(timeout=5)
        try:
            store.claim_run(run)
            return True
        except ValueError:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: claim(), range(2)))
    assert sorted(results) == [False, True]
    assert store.run(run)["state"] == "running"
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM events WHERE run=?", (run,)).fetchone()[0] == 1


def test_other_owner_and_terminal_run_cannot_be_claimed(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"files": []})
    with pytest.raises(PermissionError):
        PlatformStore(store.path, "bob").claim_run(run)
    store.transition(run, "cancelled", "cancel")
    with pytest.raises(ValueError):
        store.claim_run(run)
    assert store.run(run)["state"] == "cancelled"
