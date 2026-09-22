"""S13 导航与文案统一（先红后绿）。

验收（任务书 S13）：左侧栏可调整宽度、项目/会话完整标题、低频功能移入
"更多"、"完全访问权限"改名、"Skill"改"工具与能力"、中英文统一、
顶部导航重构、动态项目摘要。
铁律：权限模式 id（request/risk/full）与判定语义不变，只改用户可见文案。
"""
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QPushButton, QSplitter

# ------------------------------------------------------------ 权限模式文案

def test_permission_mode_full_renamed_semantics_unchanged():
    from asset_based_agent.technical_platform.agent_permission_modes import (
        permission_mode_options,
        requires_confirmation,
    )
    options = permission_mode_options()
    assert [item.id for item in options] == ['request', 'risk', 'full'], \
        '模式 id 冻结不变'
    titles = [item.title for item in options]
    assert '完全访问权限' not in titles, '任务书要求改名'
    assert titles == ['请求批准', '帮我批准', '范围内自动执行']
    assert requires_confirmation('full', 'network') is False, '判定语义不变'
    assert requires_confirmation('request', 'network') is True
    for item in options:
        assert 'Skill' not in item.title and 'Skill' not in item.description, \
            '用户可见文案不出现英文 Skill'


# ------------------------------------------------------------ Qt 集成

def _make_window(tmp_path, name='s13 项目', session='s13 会话'):
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'ui.sqlite', 'tester')
    project = store.create_project(name)
    store.create_session(project, session)
    window = PlatformWindow(store)
    window.reload_projects(project)
    return app, store, window, project


def _sidebar_buttons(window):
    return [b.text() for b in window.sidebar.findChildren(QPushButton)]


def test_skill_copy_unified_and_more_menu(tmp_path):
    app, _s, window, _p = _make_window(tmp_path)
    app.processEvents()
    texts = _sidebar_buttons(window)
    assert '工具与能力' in texts, '“能力与 Skill”改为“工具与能力”'
    assert not any('Skill' in t for t in texts), '侧栏按钮不出现英文 Skill'
    assert '审核工具' in window.version_label.text()
    assert 'Skill' not in window.version_label.text()
    # 低频功能移入“更多”
    assert '更多' in texts
    menu_texts = [a.text() for a in window.more_button.menu().actions()]
    for low_freq in ['恢复已归档会话', '恢复已归档项目', '认领旧共享项目', '检查服务版本兼容性']:
        assert low_freq in menu_texts
        assert low_freq not in texts, '低频功能不得直接占用侧栏'
    window.close()


def test_sidebar_resizable(tmp_path):
    window = _make_window(tmp_path)[2]
    splitter = window.centralWidget()
    assert isinstance(splitter, QSplitter)
    assert window.sidebar.minimumWidth() <= 200, '侧栏不得锁死最小宽度'
    assert window.sidebar.maximumWidth() >= 480, '侧栏可拖宽'
    window.close()


def test_full_titles_and_tooltips(tmp_path):
    long_name = '2026年度某集团有限责任公司重大资产重组专项审核项目（完整标题）'
    long_session = '第一次全面审核会话（含全部往来明细与凭证核查）'
    app, _s, window, _p = _make_window(
        tmp_path, name=long_name, session=long_session)
    app.processEvents()
    assert window.title.text() == long_name, '项目标题完整显示不截断'
    assert long_name in window.title.toolTip()
    tree = window.project_tree
    node = tree.topLevelItem(0)
    assert node.toolTip(0) == long_name, '项目节点 tooltip 给完整标题'
    child = node.child(0)
    assert long_session in child.toolTip(0), '会话节点 tooltip 给完整标题'
    window.close()


def test_dynamic_project_summary(tmp_path):
    app, store, window, project = _make_window(tmp_path)
    from asset_based_agent.technical_platform.skills import digest
    for name in ('a.docx', 'b.xlsx'):
        path = tmp_path / name
        path.write_bytes(b'x')
        store.add_file(project, path, digest(path))
    window.refresh_details()
    app.processEvents()
    summary = window.project_summary.text()
    assert '2 个文件' in summary
    assert '1 个会话' in summary
    assert '0 项成果' in summary
    window.close()


def test_top_nav_buttons_have_tooltips(tmp_path):
    app, _s, window, _p = _make_window(tmp_path)
    app.processEvents()
    nav = {b.text(): b for b in window.centralWidget().findChildren(QPushButton)}
    assert '项目面板' in nav and '浏览器' in nav
    assert nav['项目面板'].toolTip(), '顶部导航按钮必须有提示'
    assert nav['浏览器'].toolTip()
    window.close()
