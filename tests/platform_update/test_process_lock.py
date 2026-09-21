import multiprocessing

import pytest

from asset_based_agent.technical_platform.updates.process_lock import InstallationLock


def hold_reader(path, ready, finish):
    with InstallationLock(path).runtime():
        ready.set()
        finish.wait(20)


def test_readers_can_share_but_installer_is_exclusive(tmp_path):
    path = tmp_path / 'installation-lock.sqlite'
    InstallationLock.initialize(path)
    lock = InstallationLock(path)
    with (
        lock.runtime(), InstallationLock(path).runtime(),
        pytest.raises(BlockingIOError), lock.installation(),
    ):
        pytest.fail('installer entered live runtime')
    with lock.installation():
        with pytest.raises(BlockingIOError), lock.runtime():
            pytest.fail('runtime entered installation')
        with pytest.raises(BlockingIOError), lock.installation():
            pytest.fail('second installer entered')
    with lock.runtime():
        pass


@pytest.mark.parametrize('crash', [False, True])
def test_real_child_runtime_blocks_install_and_exit_releases_lock(tmp_path, crash):
    path = tmp_path / 'installation-lock.sqlite'
    InstallationLock.initialize(path)
    context = multiprocessing.get_context('spawn')
    ready, finish = context.Event(), context.Event()
    child = context.Process(target=hold_reader, args=(path, ready, finish))
    child.start()
    try:
        assert ready.wait(15)
        with pytest.raises(BlockingIOError), InstallationLock(path).installation():
            pytest.fail('installer ignored another process')
        if crash:
            child.terminate()  # Simulate only this synthetic runtime crashing.
        else:
            finish.set()
        child.join(15)
        assert child.exitcode is not None
        if not crash:
            assert child.exitcode == 0
        with InstallationLock(path).installation():
            pass
    finally:
        if child.is_alive():
            child.terminate()  # Only this test-owned synthetic process.
            child.join(5)


def test_missing_corrupt_or_existing_control_database_fails_closed(tmp_path):
    path = tmp_path / 'installation-lock.sqlite'
    with pytest.raises(OSError), InstallationLock(path).runtime():
        pytest.fail('missing lock must not be recreated by startup')
    path.write_bytes(b'corrupt')
    with pytest.raises(ValueError), InstallationLock(path).runtime():
        pytest.fail('invalid lock must not allow startup')
    with pytest.raises(FileExistsError):
        InstallationLock.initialize(path)
    assert path.read_bytes() == b'corrupt'

