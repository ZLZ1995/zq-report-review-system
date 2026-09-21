from pathlib import Path
from threading import Event

import pytest
from test_browser_upload_source import source


def test_upload_prepares_separate_copy_and_preserves_source(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_preparation import (
        prepare_upload,
    )
    store, session, run, path, version = source(tmp_path)
    ref = {'run_id': run, 'kind': 'generation', 'index': 0, 'sha256': version}
    result = prepare_upload(store, session, ref, Event())
    staged = Path(result['path'])
    assert staged != path and staged.name == path.name
    assert staged.read_bytes() == path.read_bytes()
    assert result['sha256'] == version
    assert staged.is_relative_to(store.path.parent / 'browser_uploads')
    second = prepare_upload(store, session, ref, Event())
    assert second['path'] != result['path']


def test_upload_cancelled_preparation_does_not_publish_copy(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_preparation import (
        prepare_upload,
    )
    store, session, run, path, version = source(tmp_path)
    cancel = Event(); cancel.set()
    ref = {'run_id': run, 'kind': 'generation', 'index': 0, 'sha256': version}
    with pytest.raises(InterruptedError): prepare_upload(store, session, ref, cancel)
    assert not (store.path.parent / 'browser_uploads').exists()
    assert path.is_file()


def test_upload_rejects_source_changed_after_copy(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import (
        browser_upload_preparation as module,
    )
    store, session, run, path, version = source(tmp_path)
    ref = {'run_id': run, 'kind': 'generation', 'index': 0, 'sha256': version}
    original = module.fingerprint_download
    def change_after_hash(*args):
        result = original(*args)
        path.write_bytes(b'changed by user during preparation')
        return result
    monkeypatch.setattr(module, 'fingerprint_download', change_after_hash)
    with pytest.raises(ValueError): module.prepare_upload(store, session, ref, Event())
    assert path.read_bytes() == b'changed by user during preparation'
    assert not list((store.path.parent / 'browser_uploads').glob('*/sample.docx'))
