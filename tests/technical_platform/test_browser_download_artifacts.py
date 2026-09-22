import json
import sqlite3
from hashlib import sha256
from threading import Event

import pytest
from test_browser_task_spec import make_browser_run


def ready(tmp_path, source_url=None, resource_url=None, *, actions=None):
    from asset_based_agent.technical_platform.browser_action_request import (
        BrowserActionRequest,
    )
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.task_spec import snapshot_identity
    store,run,_=make_browser_run(tmp_path,actions=actions or ['observe','download'])
    snapshot=json.loads(store.run(run)['snapshot']); plan=ExecutionPlan.model_validate(snapshot['execution_plan'])
    store.transition(run,'running','test'); events=ExecutionStore(store); events.register(plan)
    claim=events.claim(run,plan.steps[0].step_id)
    path=tmp_path/'file.txt'; path.write_bytes(b'synthetic-download')
    url=resource_url or 'https://example.com/file'
    binding={'url':url,'destination':str(path)}
    if source_url is not None:
        binding['source_url']=source_url
    payload=json.dumps(binding,sort_keys=True,ensure_ascii=False)
    request=BrowserActionRequest(identity=snapshot_identity(snapshot),step_id=plan.steps[0].step_id,
        revision=1,claim_token=claim,environment='test',tab_id='tab',page_version=1,
        origin='https://example.com',action='download',target='native',payload_sha256=sha256(payload.encode()).hexdigest())
    service=PermissionService(store); receipt=service.authorize_browser_action(request,confirmed=True)
    return store,run,request,receipt,path,url,service


def test_download_hash_is_cancel_safe_and_checks_actual_size(tmp_path):
    from asset_based_agent.technical_platform.browser_download_artifacts import (
        fingerprint_download,
    )
    path=tmp_path/'file.txt'; path.write_bytes(b'data')
    result=fingerprint_download(path,4,Event())
    assert result['sha256']==sha256(b'data').hexdigest()
    with pytest.raises(ValueError): fingerprint_download(path,5,Event())
    cancelled=Event(); cancelled.set()
    with pytest.raises(InterruptedError): fingerprint_download(path,4,cancelled)


def test_download_fingerprint_ignores_windows_ctime_view_difference(tmp_path, monkeypatch):
    """Path.stat and fstat may expose different Windows ctime views for one file."""
    from types import SimpleNamespace

    from asset_based_agent.technical_platform import (
        browser_download_artifacts as artifacts,
    )

    path=tmp_path/'file.txt'; path.write_bytes(b'data')
    real_fstat=artifacts.os.fstat

    def differing_ctime(fd):
        info=real_fstat(fd)
        values={name:getattr(info,name) for name in (
            'st_mode','st_nlink','st_dev','st_ino','st_size','st_mtime_ns','st_ctime_ns')}
        values['st_ctime_ns'] += 1
        return SimpleNamespace(**values)

    monkeypatch.setattr(artifacts.os,'fstat',differing_ctime)
    result=artifacts.fingerprint_download(path,4,Event())
    assert result['sha256']==sha256(b'data').hexdigest()


def test_artifact_is_persisted_once_under_consumed_authorization(tmp_path):
    from asset_based_agent.technical_platform.browser_download_artifacts import (
        DownloadArtifacts,
        fingerprint_download,
    )
    store,run,request,receipt,path,url,service=ready(tmp_path)
    payload=fingerprint_download(path,path.stat().st_size,Event())
    artifacts=DownloadArtifacts(store)
    with pytest.raises(PermissionError): artifacts.save(request,receipt,url,payload)
    service.consume_browser_action(receipt,request)
    identity=artifacts.save(request,receipt,url,payload)
    assert artifacts.save(request,receipt,url,payload)==identity
    rows=artifacts.list(run)
    assert len(rows)==1 and rows[0]['id']==identity and rows[0]['sha256']==payload['sha256']
    assert artifacts.resolve(store.run(run)['session'],run,identity)==path
    path.write_bytes(b'replaced-download')
    with pytest.raises(ValueError): artifacts.resolve(store.run(run)['session'],run,identity)


@pytest.mark.parametrize('case',['other_destination','other_origin','wrong_receipt','revoked','wrong_session'])
def test_download_artifact_rejects_unbound_or_revoked_records(tmp_path,case):
    from asset_based_agent.technical_platform.browser_download_artifacts import (
        DownloadArtifacts,
        fingerprint_download,
    )
    store,run,request,receipt,path,url,service=ready(tmp_path)
    service.consume_browser_action(receipt,request)
    payload=fingerprint_download(path,path.stat().st_size,Event())
    artifacts=DownloadArtifacts(store)
    if case=='wrong_session':
        identity=artifacts.save(request,receipt,url,payload)
        with pytest.raises(PermissionError): artifacts.resolve('other',run,identity)
        return
    if case=='other_destination': payload['path']=str(tmp_path/'other.txt')
    if case=='other_origin': url='https://other.test/file'
    if case=='wrong_receipt': receipt='wrong'
    if case=='revoked': service.revoke(run)
    with pytest.raises((PermissionError,ValueError)): artifacts.save(request,receipt,url,payload)
    assert artifacts.list(run)==[]


def test_v7_download_migration_has_backup_and_rollback(tmp_path,monkeypatch):
    from asset_based_agent.technical_platform import local_migrations as migrations
    from asset_based_agent.technical_platform.store import PlatformStore
    store=PlatformStore(tmp_path/'db.sqlite','alice')
    with store.connect() as db:
        db.execute('DROP TABLE browser_download_artifacts')
        db.execute('PRAGMA user_version=7')
    original=migrations.apply_v8
    def fail(db):
        original(db)
        raise RuntimeError('synthetic-migration-failure')
    monkeypatch.setattr(migrations,'apply_v8',fail)
    with pytest.raises(RuntimeError): migrations.migrate_database(store.path)
    with sqlite3.connect(store.path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0]==7
        assert db.execute("SELECT name FROM sqlite_master WHERE name='browser_download_artifacts'").fetchone() is None
    monkeypatch.setattr(migrations,'apply_v8',original)
    backup=migrations.migrate_database(store.path)
    with sqlite3.connect(backup) as db: assert db.execute('PRAGMA user_version').fetchone()[0]==7
    with store.connect() as db: assert db.execute('SELECT COUNT(*) FROM browser_download_artifacts').fetchone()[0]==0


def test_native_commit_uses_real_task_receipt_and_rejects_page_change(tmp_path):
    from types import SimpleNamespace

    from PySide6.QtCore import QUrl

    from asset_based_agent.technical_platform.browser_download_artifacts import (
        DownloadArtifacts,
        fingerprint_download,
    )
    from asset_based_agent.technical_platform.browser_native_download import (
        NativeTaskDownload,
    )
    store,run,request,receipt,path,url,service=ready(tmp_path, 'https://example.com/page')
    service.consume_browser_action(receipt,request)
    native=SimpleNamespace(host=SimpleNamespace(store=store),allowed=lambda *_:True,
                           page=SimpleNamespace(url=lambda:QUrl('https://example.com/page')))
    observer=SimpleNamespace(_epoch=1)
    adapter=NativeTaskDownload(native,observer,None)
    adapter.source='https://example.com/page'; adapter.url=url; adapter.page_version=1
    adapter.receipt=receipt; adapter.action_request=request
    adapter.delivered={'task_id':run,'path':str(path),'name':path.name,'size':path.stat().st_size,
                       'origin':'https://example.com'}
    data=fingerprint_download(path,path.stat().st_size,Event())
    observer._epoch=2
    with pytest.raises(PermissionError): adapter.commit_verified(data)
    assert DownloadArtifacts(store).list(run)==[]
    observer._epoch=1
    result=adapter.commit_verified(data)
    assert result['id']==DownloadArtifacts(store).list(run)[0]['id']


@pytest.mark.parametrize('resource_url', ['https://example.com/file',
    'blob:https://example.com/12345678-1234-1234-1234-123456789abc'])
def test_download_provenance_is_bound_to_authorized_source_and_persisted(tmp_path, resource_url):
    from asset_based_agent.technical_platform.browser_download_artifacts import (
        DownloadArtifacts,
        fingerprint_download,
    )
    from asset_based_agent.technical_platform.browser_upload_target import (
        upload_target_key,
    )
    source='https://example.com/projects/20'
    store,run,request,receipt,path,url,service=ready(tmp_path, source, resource_url)
    service.consume_browser_action(receipt,request)
    payload=fingerprint_download(path,path.stat().st_size,Event())
    artifacts=DownloadArtifacts(store)
    with pytest.raises(PermissionError):
        artifacts.save(request,receipt,url,payload,source_url='https://example.com/projects/21')
    identity=artifacts.save(request,receipt,url,payload,source_url=source)
    row=DownloadArtifacts(store).list(run)[0]
    assert row['provenance']=={'origin':'https://example.com',
        'target_key':upload_target_key(source), 'resource_sha256':sha256(url.encode()).hexdigest()}
    assert source not in json.dumps(row)
    assert artifacts.resolve(store.run(run)['session'],run,identity)==path


def test_legacy_download_does_not_acquire_provenance(tmp_path):
    from asset_based_agent.technical_platform.browser_download_artifacts import (
        DownloadArtifacts,
        fingerprint_download,
    )
    store,run,request,receipt,path,url,service=ready(tmp_path)
    service.consume_browser_action(receipt,request)
    artifacts=DownloadArtifacts(store)
    payload=fingerprint_download(path,path.stat().st_size,Event())
    artifacts.save(request,receipt,url,payload)
    assert artifacts.list(run)[0]['provenance'] is None
