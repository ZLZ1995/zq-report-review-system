from threading import Event

import pytest
from test_browser_upload_source import source


@pytest.mark.parametrize('kind', ['generation', 'review'])
def test_candidates_are_verified_current_conversation_metadata_only(tmp_path, kind):
    from asset_based_agent.technical_platform.browser_upload_candidates import (
        collect_upload_candidates,
    )
    store, session, run, path, version = source(tmp_path, kind)
    result = collect_upload_candidates(store, session, Event())
    assert len(result) == 1
    candidate = result[0]
    assert set(candidate) == {'artifact', 'source'}
    assert candidate['artifact']['sha256'] == version
    assert candidate['artifact']['name'] == path.name
    assert candidate['source']['run_id'] == run
    assert 'path' not in repr(result)
    other = store.create_session(store.session(session)['project'])
    assert collect_upload_candidates(store, other, Event()) == []
    path.write_bytes(b'changed')
    assert collect_upload_candidates(store, session, Event()) == []


def test_cancelled_discovery_never_publishes_candidates(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_candidates import (
        collect_upload_candidates,
    )
    store, session, *_ = source(tmp_path)
    cancel = Event(); cancel.set()
    with pytest.raises(InterruptedError):
        collect_upload_candidates(store, session, cancel)
