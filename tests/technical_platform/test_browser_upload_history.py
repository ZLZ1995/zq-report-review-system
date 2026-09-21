import json
from threading import Event

import pytest
from test_browser_upload_authorization import ready


def attempted(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_authorization import (
        UploadAuthorization,
    )
    store, run, scope, reference = ready(tmp_path)
    service = UploadAuthorization(store)
    permit = service.authorize(scope, reference, confirmed=True, cancel=Event())
    service.consume(permit, permit.scope, active=True)
    service.close()
    return store, run, scope


def test_unknown_upload_history_survives_restart_and_excludes_paths(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_history import (
        upload_history,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, scope = attempted(tmp_path)
    restored = PlatformStore(store.path, store.owner)
    records = upload_history(restored, run)
    assert len(records) == 1 and records[0]['state'] == 'unknown'
    assert records[0]['metadata']['name'] == scope.artifact.name
    assert records[0]['metadata']['sha256'] == scope.artifact.sha256
    assert records[0]['metadata']['object_label'] == scope.object_label
    assert scope.artifact.path not in json.dumps(records)
    with pytest.raises(PermissionError):
        upload_history(PlatformStore(store.path, 'another-owner'), run)


def test_unknown_upload_visible_even_without_terminal_result(tmp_path):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.app import PlatformWindow
    store, run, scope = attempted(tmp_path)
    store.interrupt_active_runs([run])
    app = QApplication.instance() or QApplication([])
    for _ in range(2):
        window = PlatformWindow(store)
        try:
            window.reload_projects(store.projects()[0]['id'])
            text = window.transcript.toPlainText()
            assert '上传结果待核对' in text
            assert scope.artifact.name in text and scope.object_label in text
            assert '不要重复上传' in text
            assert scope.artifact.path not in text
        finally:
            window.close()
            app.processEvents()


def test_v9_attempt_migrates_without_inventing_metadata(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_history import (
        upload_history,
        upload_history_html,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, _ = attempted(tmp_path)
    store.interrupt_active_runs([run])
    with store.connect() as db:
        db.execute('ALTER TABLE browser_upload_attempts DROP COLUMN metadata')
        db.execute('PRAGMA user_version=9')
    restored = PlatformStore(store.path, store.owner)
    records = upload_history(restored, run)
    assert len(records) == 1 and records[0]['metadata'] is None
    assert records[0]['state'] == 'unknown'
    assert '旧版记录缺少' in upload_history_html(restored, run)
    assert list((store.path.parent / 'migration-backups').glob('*-v9-*.sqlite'))


def test_history_escapes_labels_and_rejects_extra_metadata(tmp_path):
    from asset_based_agent.technical_platform.browser_upload_history import (
        upload_history_html,
    )
    store, run, _ = attempted(tmp_path)
    with store.connect() as db:
        raw = json.loads(db.execute('SELECT metadata FROM browser_upload_attempts').fetchone()[0])
        raw['object_label'] = '<a href="zq-delete:all">misleading</a>'
        db.execute('UPDATE browser_upload_attempts SET metadata=?', (json.dumps(raw),))
    rendered = upload_history_html(store, run)
    assert '<a href=' not in rendered and '&lt;a href=' in rendered
    raw['path'] = 'synthetic-forbidden-path'
    with store.connect() as db:
        db.execute('UPDATE browser_upload_attempts SET metadata=?', (json.dumps(raw),))
    with pytest.raises(ValueError):
        upload_history_html(store, run)
