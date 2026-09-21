import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore


def test_message_branch_link_is_not_rendered(tmp_path, monkeypatch):
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent = store.create_session(project, 'parent')
    store.append(parent, 'assistant', 'source fact')
    message = store.messages(parent)[0]
    window = PlatformWindow(store)
    try:
        window.reload_projects(project)
        window.composer.setPlainText('private draft')
        link = f"zq-branch:{parent}/{message['id']}"
        assert link not in window.transcript.toHtml()
        assert '从此消息创建分支' not in window.transcript.toPlainText()
        assert window.session_id == parent
    finally:
        qt.processEvents()
        window.close()


def test_stale_branch_link_cannot_fork_another_session(tmp_path, monkeypatch):
    from asset_based_agent.technical_platform import app as ui
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent, other = store.create_session(project), store.create_session(project)
    store.append(parent, 'user', 'anchor')
    message = store.messages(parent)[0]
    window = PlatformWindow(store)
    try:
        window.reload_projects(project)
        window.reload_sessions(other)
        monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args, **kwargs: ('must not create', True))
        window.handle_report_link(QUrl(f"zq-branch:{parent}/{message['id']}"))
        assert len(store.sessions(project)) == 2
        assert window.session_id == other
    finally:
        qt.processEvents()
        window.close()


@pytest.mark.parametrize('case', ['cancel', 'wrong_anchor', 'query'])
def test_branch_cancel_or_invalid_anchor_never_creates_child(tmp_path, monkeypatch, case):
    from asset_based_agent.technical_platform import app as ui
    qt = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('p')
    parent, other = store.create_session(project), store.create_session(project)
    store.append(parent, 'user', 'parent anchor')
    store.append(other, 'assistant', 'foreign anchor')
    window = PlatformWindow(store)
    try:
        window.reload_projects(project)
        window.reload_sessions(parent)
        monkeypatch.setattr(ui.QInputDialog, 'getText', lambda *args, **kwargs: ('child', case != 'cancel'))
        anchor = store.messages(other if case == 'wrong_anchor' else parent)[0]['id']
        link = f'zq-branch:{parent}/{anchor}' + ('?overwrite=true' if case == 'query' else '')
        window.handle_report_link(QUrl(link))
        assert len(store.sessions(project)) == 2
        assert window.session_id == parent
        assert not store.runs(parent)
    finally:
        qt.processEvents()
        window.close()
