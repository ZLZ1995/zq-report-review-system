from pathlib import Path

from asset_based_agent.technical_platform.skills import digest
from asset_based_agent.technical_platform.store import PlatformStore


def test_attachment_versions_remain_readable_after_original_changes(tmp_path):
    source = tmp_path / "report.docx"
    source.write_bytes(b"version one")
    store = PlatformStore(tmp_path / "data" / "p.sqlite", "alice")
    project = store.create_project("A")
    store.add_file(project, source, digest(source))
    source.write_bytes(b"version two")
    store.add_file(project, source, digest(source))
    files = store.files(project)
    assert Path(files[0]["path"]).read_bytes() == b"version one"
    assert Path(files[1]["path"]).read_bytes() == b"version two"
    assert source.read_bytes() == b"version two"


def test_archive_restore_and_checkpoint_are_owner_scoped(tmp_path):
    store = PlatformStore(tmp_path / "p.sqlite", "alice")
    project = store.create_project("A")
    session = store.create_session(project)
    run = store.start_run(session, {})
    other = PlatformStore(tmp_path / "p.sqlite", "bob")
    other.interrupt_active_runs()
    assert store.run(run)["state"] == "queued"
    store.interrupt_active_runs()
    assert store.run(run)["state"] == "interrupted"
    store.archive(project)
    assert store.projects() == []
    assert store.archived_projects()[0]["id"] == project
    assert other.archived_projects() == []
    store.restore(project)
    assert store.projects()[0]["id"] == project


def test_exit_checkpoint_does_not_interrupt_another_window_task(tmp_path):
    store = PlatformStore(tmp_path / "p.sqlite", "alice")
    session = store.create_session(store.create_project("A"))
    first, second = store.start_run(session, {}), store.start_run(session, {})
    store.interrupt_active_runs([first])
    assert store.run(first)["state"] == "interrupted"
    assert store.run(second)["state"] == "queued"
