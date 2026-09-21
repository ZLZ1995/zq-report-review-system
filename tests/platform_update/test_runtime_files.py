import pytest

from asset_based_agent.technical_platform.updates.runtime_files import (
    configure_webengine_helper,
)


def test_pending_webengine_helper_is_used_without_creating_a_second_exe(tmp_path):
    application = tmp_path / 'ZQ技术平台'
    helper = application / '_internal/PySide6/QtWebEngineProcess.exe'
    pending = helper.with_suffix('.pending')
    pending.parent.mkdir(parents=True)
    pending.write_bytes(b'signed-helper')

    environment: dict[str, str] = {}
    assert configure_webengine_helper(application, environment=environment) == pending
    assert pending.read_bytes() == b'signed-helper'
    assert not helper.exists()
    assert configure_webengine_helper(application, environment=environment) == pending
    assert environment['QTWEBENGINEPROCESS_PATH'] == str(pending)


def test_development_tree_can_use_the_normal_exe_helper(tmp_path):
    application = tmp_path / 'ZQ\u6280\u672f\u5e73\u53f0'
    helper = application / '_internal/PySide6/QtWebEngineProcess.exe'
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b'development-helper')
    environment: dict[str, str] = {}

    assert configure_webengine_helper(application, environment=environment) == helper
    assert environment['QTWEBENGINEPROCESS_PATH'] == str(helper)


def test_missing_or_ambiguous_webengine_helper_fails_closed(tmp_path):
    application = tmp_path / 'ZQ技术平台'
    helper = application / '_internal/PySide6/QtWebEngineProcess.exe'
    pending = helper.with_suffix('.pending')
    pending.parent.mkdir(parents=True)
    with pytest.raises(FileNotFoundError):
        configure_webengine_helper(application)
    helper.write_bytes(b'installed')
    pending.write_bytes(b'unexpected-second-copy')
    with pytest.raises(ValueError, match='ambiguous'):
        configure_webengine_helper(application)
