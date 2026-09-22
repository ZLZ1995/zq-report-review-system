"""S10 执行记录与消息层级（先红后绿）。

验收（任务书 S10）：执行记录折叠、SystemEventCard、UserMessageCard、
AssistantMessageCard、WarningCard、ErrorCard、Error detail、diagnostics copy。
铁律：错误卡不得暴露 traceback/凭据；折叠不丢内容；层级语义来自真实
entry 类型与 severity。
"""
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.message_cards import (
    assistant_card_html,
    diagnostics_text,
    error_card_html,
    execution_group_html,
    system_event_card_html,
    user_card_html,
    warning_card_html,
)

# ------------------------------------------------------------ 卡片构建器

def test_user_card_html():
    rendered = user_card_html('审核 <b>报告</b>')
    assert '审核 &lt;b&gt;报告&lt;/b&gt;' in rendered, '用户文本必须转义'
    assert '你' in rendered


def test_assistant_card_html():
    rendered = assistant_card_html('结论如下')
    assert 'ZQ' in rendered and '结论如下' in rendered


def test_system_event_card_html():
    rendered = system_event_card_html('已生成快照')
    assert '执行记录' in rendered and '已生成快照' in rendered


def test_warning_card_html():
    rendered = warning_card_html('用量接近上限')
    assert '警告' in rendered and '用量接近上限' in rendered


def test_error_card_html_with_detail_and_diagnostics_link():
    rendered = error_card_html('本轮未完成。', error_code='model.timeout',
                               operation_id='op-abcdef123456')
    assert '失败' in rendered
    assert '本轮未完成。' in rendered
    assert 'model.timeout' in rendered, 'Error detail 必须显示安全错误码'
    assert 'op-abcdef' in rendered, 'Error detail 必须显示任务 id'
    assert 'zq-diagnostics:op-abcdef123456' in rendered, \
        '必须提供 diagnostics copy 入口'


def test_diagnostics_text_contains_no_secrets_or_traceback():
    text = diagnostics_text(operation_id='op-1', error_code='model.timeout',
                            summary='本轮未完成。', client_version='1.2.3')
    assert 'op-1' in text and 'model.timeout' in text and '1.2.3' in text
    assert 'Traceback' not in text and 'password' not in text.lower()


def test_execution_group_html_collapsed_and_expanded():
    events = ['第一步完成', '第二步完成', '第三步完成', '第四步完成']
    collapsed = execution_group_html(events, group_id='g1', collapsed=True)
    assert '执行记录（4 条）' in collapsed
    assert '第四步完成' in collapsed, '折叠卡必须显示最近一条'
    assert '第一步完成' not in collapsed, '折叠态隐藏历史条目'
    assert 'zq-events:g1' in collapsed, '必须有展开入口'
    expanded = execution_group_html(events, group_id='g1', collapsed=False)
    for event in events:
        assert event in expanded, '展开态不得丢任何记录'


# ------------------------------------------------------------ Qt 集成

def _make_window(tmp_path):
    from asset_based_agent.technical_platform.agent_switch import (
        flags_store_for,
    )
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('s10 项目')
    session = store.create_session(project, 's10 会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    assert window.session_id == session
    flags_store_for(store).set_enabled('chat', True)
    return app, store, window, session


def test_execution_records_fold_and_expand_via_link(tmp_path):
    _app, store, window, session = _make_window(tmp_path)
    store.append(session, 'user', '执行任务')
    for index in range(5):
        store.append(session, 'event', f'执行步骤 {index}')
    store.append(session, 'assistant', '完成')
    window.render_messages()
    text = window.transcript.toPlainText()
    assert '执行记录（5 条）' in text, '三条以上连续执行记录必须折叠'
    assert '执行步骤 0' not in text
    assert '执行步骤 4' in text, '折叠卡显示最近一条'

    # 展开
    key = next(iter(window._expanded_event_groups_snapshot()))
    window.handle_report_link(QUrl(f'zq-events:{key}'))
    text = window.transcript.toPlainText()
    for index in range(5):
        assert f'执行步骤 {index}' in text, '展开后不得丢记录'

    # 再点收起
    window.handle_report_link(QUrl(f'zq-events:{key}'))
    text = window.transcript.toPlainText()
    assert '执行记录（5 条）' in text
    assert '执行步骤 0' not in text
    window.close()


def test_error_message_renders_error_card_with_diagnostics_copy(tmp_path):
    _app, store, window, session = _make_window(tmp_path)
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    repo = SQLiteSessionRepo(store.path, store.owner)
    repo.create_session(session, project_id='p1', owner_id=store.owner,
                        title='会话')
    operation = repo.begin_operation(session, 'main', user_text='问',
                                     request_id='r-s10')
    repo.append_entry(session, 'main', 'error_message',
                      {'text': '本轮未完成。', 'error_code': 'model.timeout'},
                      operation_id=operation.id)
    window.render_messages()
    text = window.transcript.toPlainText()
    assert '失败' in text and '本轮未完成。' in text
    assert 'model.timeout' in text, '错误详情必须显示错误码'

    # diagnostics copy：复制到剪贴板且不含敏感内容
    QGuiApplication.clipboard().clear()
    window.handle_report_link(
        QUrl(f'zq-diagnostics:{operation.id}/model.timeout'))
    copied = QGuiApplication.clipboard().text()
    assert operation.id in copied and 'model.timeout' in copied
    assert 'Traceback' not in copied
    window.close()


def test_two_consecutive_events_stay_unfolded(tmp_path):
    _app, store, window, session = _make_window(tmp_path)
    store.append(session, 'event', '步骤甲')
    store.append(session, 'event', '步骤乙')
    window.render_messages()
    text = window.transcript.toPlainText()
    assert '步骤甲' in text and '步骤乙' in text, '少量记录不得折叠'
    assert '执行记录（' not in text
    window.close()
