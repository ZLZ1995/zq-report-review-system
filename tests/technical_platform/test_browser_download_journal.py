import sqlite3

import pytest

from asset_based_agent.technical_platform.browser_downloads import DownloadTarget


def journal_at(tmp_path):
    from asset_based_agent.technical_platform.browser_download_journal import (
        DownloadJournal,
    )
    profile = tmp_path/'profile'
    profile.mkdir(exist_ok=True)
    return DownloadJournal(profile/'downloads.sqlite')


def test_recovery_removes_only_registered_stage_and_keeps_final(tmp_path):
    journal = journal_at(tmp_path)
    target = DownloadTarget(tmp_path/'result.txt')
    journal.track(target)
    target.partial.write_bytes(b'partial')
    target.destination.write_bytes(b'previous final')
    unrelated = tmp_path/'.zq-download-unregistered'
    unrelated.mkdir()
    assert journal.recover() == (1, 0)
    assert target.destination.read_bytes() == b'previous final'
    assert unrelated.is_dir()
    assert not target.stage.exists()
    assert journal.recover() == (0, 0)


def test_recovery_retains_unknown_entries_and_replaced_directory(tmp_path):
    journal = journal_at(tmp_path)
    first = DownloadTarget(tmp_path/'first.txt')
    second = DownloadTarget(tmp_path/'second.txt')
    journal.track(first); journal.track(second)
    first.partial.write_bytes(b'partial')
    (first.stage/'keep.txt').write_bytes(b'user')
    old = second.stage.with_name(second.stage.name+'-moved')
    second.stage.rename(old)
    second.stage.mkdir()
    second.partial.write_bytes(b'replacement')
    assert journal.recover() == (0, 2)
    assert first.partial.read_bytes() == b'partial'
    assert second.partial.read_bytes() == b'replacement'


def test_journal_forget_never_deletes_payload(tmp_path):
    journal = journal_at(tmp_path)
    target = DownloadTarget(tmp_path/'result.txt')
    journal.track(target)
    target.partial.write_bytes(b'keep')
    journal.forget(target.stage)
    assert journal.recover() == (0, 0)
    assert target.partial.read_bytes() == b'keep'


def test_unknown_journal_schema_refused(tmp_path):
    journal = journal_at(tmp_path)
    with sqlite3.connect(journal.path) as db:
        db.execute('PRAGMA user_version=999')
    with pytest.raises(ValueError):
        journal.recover()


def test_journal_tampered_broad_path_cannot_delete_business_file(tmp_path):
    journal = journal_at(tmp_path)
    target = DownloadTarget(tmp_path/'result.txt')
    journal.track(target)
    victim = tmp_path/'payload.part'
    victim.write_bytes(b'business data')
    with sqlite3.connect(journal.path) as db:
        db.execute('UPDATE stages SET stage=?', (str(tmp_path),))
    assert journal.recover() == (0, 1)
    assert victim.read_bytes() == b'business data'
