from pathlib import Path

import pytest


@pytest.mark.parametrize('name', ['../a.txt', 'C:\\a.txt', 'CON.txt', 'NUL',
                                  'a.txt:stream', 'a.txt.', 'a?.txt', '', 'a\n.txt'])
def test_download_name_rejects_unsafe_windows_paths(name):
    from asset_based_agent.technical_platform.browser_downloads import validate_filename
    with pytest.raises(ValueError):
        validate_filename(name)


def test_download_stages_then_publishes_without_overwrite(tmp_path):
    from asset_based_agent.technical_platform.browser_downloads import DownloadTarget
    destination = tmp_path/'下载.txt'
    target = DownloadTarget(destination)
    assert not destination.exists()
    target.partial.write_bytes(b'synthetic download')
    target.publish()
    assert destination.read_bytes() == b'synthetic download'
    assert not target.stage.exists()
    with pytest.raises(FileExistsError):
        DownloadTarget(destination)


def test_download_late_collision_preserves_both_files(tmp_path):
    from asset_based_agent.technical_platform.browser_downloads import DownloadTarget
    destination = tmp_path/'result.txt'
    target = DownloadTarget(destination)
    target.partial.write_bytes(b'new')
    destination.write_bytes(b'previous')
    with pytest.raises(FileExistsError):
        target.publish()
    assert destination.read_bytes() == b'previous'
    assert target.partial.read_bytes() == b'new'


def test_download_cancel_does_not_publish_or_delete_unrelated(tmp_path):
    from asset_based_agent.technical_platform.browser_downloads import DownloadTarget
    target = DownloadTarget(tmp_path/'result.txt')
    target.partial.write_bytes(b'partial')
    other = tmp_path/'keep.txt'
    other.write_bytes(b'keep')
    target.discard()
    assert not target.stage.exists()
    assert not target.destination.exists()
    assert other.read_bytes() == b'keep'


def test_system_drive_and_relative_download_rejected(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform.browser_downloads import DownloadTarget
    with pytest.raises(ValueError):
        DownloadTarget(Path('relative.txt'))
    monkeypatch.setenv('SystemDrive', tmp_path.drive)
    with pytest.raises(ValueError):
        DownloadTarget(tmp_path/'result.txt')


def test_completed_download_retains_success_when_empty_stage_cleanup_fails(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform.browser_downloads import DownloadTarget
    target = DownloadTarget(tmp_path/'result.txt')
    target.partial.write_bytes(b'complete')
    original = Path.rmdir

    def fail_stage(path):
        if path == target.stage:
            raise PermissionError('synthetic busy directory')
        return original(path)

    monkeypatch.setattr(Path, 'rmdir', fail_stage)
    assert target.publish() == target.destination
    assert target.destination.read_bytes() == b'complete'
    assert target.cleanup_pending
