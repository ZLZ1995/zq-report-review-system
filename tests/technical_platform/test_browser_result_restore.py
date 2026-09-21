import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.store import PlatformStore


@pytest.mark.parametrize('state,status,verified,expected', [
    ('cancelled', 'cancelled', False, '已取消'),
    ('failed', 'unknown', False, '尚未通过完成验证'),
    ('failed', 'needs_input', False, '需要补充信息'),
    ('failed', 'needs_verification', True, '尚未通过完成验证'),
    ('succeeded', 'needs_verification', True, '通过结果验证'),
])
def test_browser_restore_uses_task_state_not_preflight_and_is_idempotent(
        tmp_path, state, status, verified, expected):
    app = QApplication.instance() or QApplication([])
    assert app is not None
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('browser')
    session = store.create_session(project)
    run = store.start_run(session, {'files': []})
    store.transition(run, 'running', 'synthetic')
    if state == 'succeeded':
        store.transition(run, 'validating', 'synthetic')
    store.transition(run, state, 'synthetic')
    result = {'kind': 'browser', 'status': status, 'verified': verified,
              'summary': 'Synthetic website summary', 'evidence': 'Synthetic evidence'}
    with store.connect() as db:
        db.execute('UPDATE runs SET result=? WHERE id=?', (json.dumps(result), run))
    for _ in range(2):
        window = PlatformWindow(store)
        try:
            window.reload_projects(project)
            text = window.transcript.toPlainText()
            assert expected in text
            assert '资料预检结果' not in text
            assert '未调用大模型' not in text
            assert text.count('Synthetic website summary') == 1
            assert '网页依据（未经独立信任）' in text
            window.run_id = run
            window.completed(result)
            assert window.transcript.toPlainText().count('Synthetic website summary') == 1
        finally:
            window.close()
