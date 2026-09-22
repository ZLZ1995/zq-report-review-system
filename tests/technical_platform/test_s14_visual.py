"""S14 视觉层级和密度优化（先红后绿）。

验收（任务书 S14）：对比度、间距、卡片层级、最大内容宽度、系统日志压缩、
当前选中状态、运行中状态色、错误/警告/成功色。
铁律：对比度阈值不得放宽（正文/状态文字 ≥4.5，WCAG AA）；
颜色单一事实源为 ui_theme.py，run_status/message_cards/app 样式必须引用它。
"""
from __future__ import annotations

import os
import re

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform import ui_theme
from asset_based_agent.technical_platform.ui_theme import (
    CONTRAST_PAIRS,
    LOG_FONT_SIZE,
    MAX_CONTENT_WIDTH,
    SPACING,
    contrast_ratio,
)

# ------------------------------------------------------------ 调色板

def test_contrast_pairs_meet_declared_standard():
    assert len(CONTRAST_PAIRS) >= 10, '关键文字/背景对必须全部登记'
    for name, fg, bg, minimum in CONTRAST_PAIRS:
        actual = contrast_ratio(fg, bg)
        assert actual >= minimum, \
            f'{name}: {fg} on {bg} = {actual:.2f} < {minimum}'


def test_state_colors_distinct_and_valid():
    colors = [ui_theme.RUNNING, ui_theme.ERROR, ui_theme.WARNING,
              ui_theme.SUCCESS, ui_theme.UNKNOWN]
    for color in colors:
        assert re.fullmatch(r'#[0-9a-f]{6}', color), '统一小写 hex'
    assert len(set(colors)) == 5, '五种状态色必须可区分'


def test_spacing_scale_and_layout_limits():
    assert list(SPACING) == sorted(SPACING)
    assert all(v % 4 == 0 for v in SPACING), '间距刻度为 4 的倍数'
    assert 960 <= MAX_CONTENT_WIDTH <= 1280
    assert LOG_FONT_SIZE <= 12, '系统日志压缩为小字号'


def test_card_backgrounds_distinct():
    backgrounds = {ui_theme.CARD_BG_NEUTRAL, ui_theme.CARD_BG_STATUS,
                   ui_theme.CARD_BG_WARNING, ui_theme.CARD_BG_ERROR,
                   ui_theme.CARD_BG_SUCCESS}
    assert len(backgrounds) == 5, '卡片层级背景必须可区分'


# ------------------------------------------------------------ 引用一致性

def test_run_status_uses_theme_colors():
    from asset_based_agent.technical_platform import run_status
    assert run_status._STATE_COLORS['running'] == ui_theme.RUNNING
    assert run_status._STATE_COLORS['failed'] == ui_theme.ERROR
    assert run_status._STATE_COLORS['completed'] == ui_theme.SUCCESS
    assert run_status._STATE_COLORS['waiting_user'] == ui_theme.WARNING
    assert run_status._STATE_COLORS['unknown'] == ui_theme.UNKNOWN


def test_status_card_html_uses_theme():
    from asset_based_agent.technical_platform.run_status import (
        RunStatusView,
        status_card_html,
        terminal_line_html,
    )
    view = RunStatusView(state='running', operation_id='op123456789',
                         elapsed_seconds=5, last_activity_seconds=1,
                         step_index=1, text='')
    html_text = status_card_html(view)
    assert ui_theme.RUNNING in html_text
    assert ui_theme.CARD_BG_STATUS in html_text
    failed = terminal_line_html(RunStatusView(
        state='failed', operation_id='op123456789', elapsed_seconds=5,
        last_activity_seconds=None, step_index=3, text=''))
    assert ui_theme.ERROR in failed


def test_message_cards_use_theme_colors():
    from asset_based_agent.technical_platform.message_cards import (
        error_card_html,
        warning_card_html,
    )
    warning = warning_card_html('注意')
    assert ui_theme.WARNING in warning and ui_theme.CARD_BG_WARNING in warning
    error = error_card_html('失败', error_code='E1', operation_id='op123456789')
    assert ui_theme.ERROR in error and ui_theme.CARD_BG_ERROR in error


def test_system_log_compressed():
    from asset_based_agent.technical_platform.message_cards import (
        execution_group_html,
        system_event_card_html,
    )
    event = system_event_card_html('一条执行记录')
    assert f'font-size:{LOG_FONT_SIZE}px' in event
    assert 'line-height:140%' in event, '系统日志行高压到 140%'
    group = execution_group_html(['a', 'b', 'c'], group_id='g', collapsed=False)
    assert f'font-size:{LOG_FONT_SIZE}px' in group


# ------------------------------------------------------------ Qt 集成

def _make_window(tmp_path):
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'ui.sqlite', 'tester')
    project = store.create_project('s14 项目')
    store.create_session(project, 's14 会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    return app, store, window, project


def test_max_content_width_applied(tmp_path):
    app, _s, window, _p = _make_window(tmp_path)
    app.processEvents()
    assert window.transcript.maximumWidth() == MAX_CONTENT_WIDTH
    window.close()


def test_selection_and_overrides_in_stylesheet(tmp_path):
    app, _s, window, _p = _make_window(tmp_path)
    app.processEvents()
    qss = window.styleSheet()
    assert ui_theme.SELECTION_BG in qss and ':item:selected' in qss, \
        '当前选中状态必须有可见底色'
    assert ui_theme.MUTED in qss, '对比度修正后的次要文字色必须生效'
    assert ui_theme.RUNNING in qss, '运行中状态色必须进入全局样式'
    window.close()
