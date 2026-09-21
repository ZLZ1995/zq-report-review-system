import json
import os

import pytest

from asset_based_agent.report_review_app.repositories.project_repository import (
    ProjectRepository,
)
from asset_based_agent.report_review_app.services.audit_orchestrator import (
    _write_json_atomic,
)


@pytest.fixture(params=[ProjectRepository._write_json_atomic, _write_json_atomic])
def writer(request):
    return request.param


def denied(code=5):
    error = PermissionError('synthetic Windows file contention')
    error.winerror = code
    return error


def test_transient_windows_denial_retries_without_removing_old_file(tmp_path, monkeypatch, writer):
    target = tmp_path / 'state.json'
    target.write_text('{"state":"old"}', encoding='utf-8')
    original = os.replace
    attempts = []

    def replace(source, destination):
        attempts.append(source)
        assert json.loads(target.read_text()) == {'state': 'old'}
        if len(attempts) < 3:
            raise denied()
        return original(source, destination)

    monkeypatch.setattr(os, 'replace', replace)
    writer(target, {'state': 'new'})
    assert len(attempts) == 3
    assert json.loads(target.read_text()) == {'state': 'new'}


def test_permanent_denial_is_bounded_and_preserves_old_file(tmp_path, monkeypatch, writer):
    target = tmp_path / 'state.json'
    target.write_text('{"state":"old"}', encoding='utf-8')
    attempts = []

    def replace(*args):
        attempts.append(args)
        raise denied()

    monkeypatch.setattr(os, 'replace', replace)
    with pytest.raises(PermissionError):
        writer(target, {'state': 'new'})
    assert 1 <= len(attempts) <= 4
    assert json.loads(target.read_text()) == {'state': 'old'}


def test_interleaved_writers_do_not_share_temporary_file(tmp_path, monkeypatch, writer):
    target = tmp_path / 'state.json'
    original = os.replace
    attempts = []

    def replace(source, destination):
        attempts.append(source)
        if len(attempts) == 1:
            writer(target, {'state': 'inner'})
        return original(source, destination)

    monkeypatch.setattr(os, 'replace', replace)
    writer(target, {'state': 'outer'})
    assert len(set(attempts)) == 2
    assert json.loads(target.read_text()) == {'state': 'outer'}


def test_unrelated_permission_error_is_not_retried(tmp_path, monkeypatch, writer):
    calls = []
    def replace(*args):
        calls.append(args)
        raise PermissionError('not a Windows contention code')
    monkeypatch.setattr(os, 'replace', replace)
    with pytest.raises(PermissionError):
        writer(tmp_path / 'state.json', {'state': 'new'})
    assert len(calls) == 1


@pytest.mark.skipif(os.name != 'nt', reason='Windows file sharing test')
@pytest.mark.parametrize('extra_denial', [False, True])
def test_actual_windows_open_handle_can_release_during_retry(tmp_path, monkeypatch, writer, extra_denial):
    import win32con
    import win32file

    from asset_based_agent.report_review_app import atomic_json
    target = tmp_path / 'state.json'
    target.write_text('{"state":"old"}', encoding='utf-8')
    handle = win32file.CreateFile(
        str(target), win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE,
        None, win32con.OPEN_EXISTING, 0, None,
    )
    released = []
    delays = []
    original_sleep = atomic_json.time.sleep
    original_replace = os.replace
    injected = []
    def replace(source, destination):
        if extra_denial and released and not injected:
            injected.append(True)
            raise denied(32)
        return original_replace(source, destination)
    monkeypatch.setattr(os, 'replace', replace)
    def release(_delay):
        assert json.loads(target.read_text()) == {'state': 'old'}
        delays.append(_delay)
        if not released:
            handle.Close()
            released.append(True)
        original_sleep(_delay)
    monkeypatch.setattr(atomic_json.time, 'sleep', release)
    try:
        writer(target, {'state': 'new'})
        assert released == [True]
        assert 1 <= len(delays) <= 3
        assert bool(injected) == extra_denial
        assert json.loads(target.read_text()) == {'state': 'new'}
    finally:
        if not released:
            handle.Close()
