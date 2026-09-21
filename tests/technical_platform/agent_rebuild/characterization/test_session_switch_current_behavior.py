"""S01 现状冻结：会话切换与渲染。

已知缺陷（xfail）：SES-11 打开历史会话会经 show_result/append_output 写入消息；
SES-15 后台失败状态不写回所属 session。
"""
import pytest
from conftest import failing_consult_worker
from test_consultation_routing import make_store


def _window(store, monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.app import PlatformWindow
    QApplication.instance() or QApplication([])
    return PlatformWindow(store)


def _completed_run(store, session):
    run_id = store.start_run(session, {'goal': '审核'})
    store.transition(run_id, 'running', 't')
    store.transition(run_id, 'validating', 't')
    store.transition(run_id, 'succeeded', 't')
    store.save_result(run_id, {'kind': 'review', 'files': [], 'issues': []})
    return run_id


@pytest.mark.xfail(reason='SES-11：打开历史会话触发 append_output 写入，渲染不是纯读', strict=True)
def test_opening_historical_session_does_not_write_messages(tmp_path, monkeypatch):
    store, project, session = make_store(tmp_path)
    _completed_run(store, session)
    before = [(m['role'], m['text']) for m in store.messages(session)]
    window = _window(store, monkeypatch)
    try:
        window.reload_projects(project)
        window.reload_sessions(session)
        window.render_messages()
        window.render_messages()
    finally:
        window.close()
    after = [(m['role'], m['text']) for m in store.messages(session)]
    assert after == before, '打开/渲染会话不得新增或修改消息'


@pytest.mark.xfail(reason='SES-15：后台咨询失败不写回原 session，状态与会话脱钩', strict=True)
def test_background_failure_is_written_to_owning_session(tmp_path):
    store, project, first = make_store(tmp_path)
    second = store.create_session(project)
    _spy, worker = failing_consult_worker(store, first, '你能帮我做什么')
    assert worker.error
    first_roles = [m['role'] for m in store.messages(first)]
    assert first_roles == ['user', 'assistant'], '失败必须写回发起会话'
    assert store.messages(second) == [], '失败不得串入其他会话'
