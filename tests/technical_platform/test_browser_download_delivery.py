import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from threading import Event

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication
from test_browser_download_artifacts import ready

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.browser_download_artifacts import (
    DownloadArtifacts,
    fingerprint_download,
)


def saved(tmp_path):
    store, run, request, receipt, path, url, service = ready(tmp_path)
    service.consume_browser_action(receipt, request)
    item = fingerprint_download(path, path.stat().st_size, Event())
    identity = DownloadArtifacts(store).save(request, receipt, url, item)
    store.transition(run, 'cancelled', 'synthetic terminal')
    with store.connect() as db:
        db.execute("UPDATE runs SET result=? WHERE id=?", ('{"kind":"browser"}', run))
    return store, run, identity, path


def test_download_visible_after_task_cancel_and_window_restart(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store, run, identity, path = saved(tmp_path)
    opened = []
    monkeypatch.setattr('asset_based_agent.technical_platform.app.QDesktopServices.openUrl',
                        lambda url: opened.append(url.toLocalFile()) or True)
    for _ in range(2):
        window = PlatformWindow(store)
        try:
            window.reload_projects(store.projects()[0]['id'])
            assert '下载时完整性已校验' in window.transcript.toPlainText()
            assert '业务内容待核验' in window.transcript.toPlainText()
            assert path.name in window.transcript.toPlainText()
            window.handle_report_link(QUrl(f'zq-download-folder:{run}/{identity}'))
            assert opened[-1] == str(path.parent).replace('\\', '/')
            count = len(opened)
            window.handle_report_link(QUrl(f'zq-download-folder:{run}/{identity}?redirect=other'))
            assert len(opened) == count
            window.resize(1280, 850)
            window.show()
            app.processEvents()
            assert window.grab().save(str(tmp_path / 'download-conversation.png'))
        finally:
            window.close()


def test_download_folder_rejects_wrong_session_and_changed_file(tmp_path):
    from asset_based_agent.technical_platform.browser_download_delivery import (
        download_folder,
    )
    store, run, identity, path = saved(tmp_path)
    session = store.run(run)['session']
    with pytest.raises(PermissionError):
        download_folder(store, 'wrong', run, identity)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError):
        download_folder(store, session, run, identity)
