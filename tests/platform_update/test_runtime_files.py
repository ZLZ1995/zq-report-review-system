import pytest

from asset_based_agent.technical_platform.updates.runtime_files import (
    restore_webengine_helper,
)


def test_pending_webengine_helper_is_atomically_restored(tmp_path):
    application = tmp_path / 'ZQ技术平台'
    helper = application / '_internal/PySide6/QtWebEngineProcess.exe'
    pending = helper.with_suffix('.pending')
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b'signed-helper')

    assert restore_webengine_helper(application) == helper
    assert helper.read_bytes() == b'signed-helper'
    assert not pending.exists()
    assert restore_webengine_helper(application) == helper


def test_missing_or_ambiguous_webengine_helper_fails_closed(tmp_path):
    application = tmp_path / 'ZQ技术平台'
    helper = application / '_internal/PySide6/QtWebEngineProcess.exe'
    pending = helper.with_suffix('.pending')
    pending.parent.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        restore_webengine_helper(application)
    helper.write_bytes(b'installed')
    pending.write_bytes(b'unexpected-second-copy')
    with pytest.raises(ValueError, match='ambiguous'):
        restore_webengine_helper(application)
