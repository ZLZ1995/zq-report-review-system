"""S9 运行状态视图模型：实时状态卡 + Stepper + 终态摘要。

铁律（任务书 S9 / 第 11 节）：
- 状态来自真实任务状态（operation/job/控制器相位），不造假 UI 状态机；
- 卡片携带真实 operation_id；
- 无真实百分比时只显示步骤进度（RunStatusView 不设 percent 字段）；
- unknown 显示"状态待核对"，绝不显示成"失败"。
"""
from __future__ import annotations

import html
from dataclasses import dataclass

from .ui_theme import (
    CARD_BG_STATUS,
    ERROR,
    LOG,
    MUTED,
    RUNNING,
    SUCCESS,
    UNKNOWN,
    WARNING,
)

RUN_STEPS = ('提交任务', '模型生成', '工具执行', '汇总结果')

RUN_STATES = frozenset({
    'queued', 'running', 'waiting_user', 'stopping',
    'completed', 'failed', 'cancelled', 'unknown',
})

RUN_STATE_LABELS = {
    'queued': '排队中',
    'running': '运行中',
    'waiting_user': '等待你的确认',
    'stopping': '正在停止',
    'completed': '已完成',
    'failed': '失败',
    'cancelled': '已取消',
    'unknown': '状态待核对',
}

_STATE_COLORS = {
    'queued': LOG,
    'running': RUNNING,
    'waiting_user': WARNING,
    'stopping': WARNING,
    'completed': SUCCESS,
    'failed': ERROR,
    'cancelled': LOG,
    'unknown': UNKNOWN,
}

_WAITING_OPERATION_STATUSES = frozenset({'waiting_approval', 'waiting_input'})
_TERMINAL_PHASES = frozenset({'completed', 'failed', 'cancelled', 'unknown'})


@dataclass(frozen=True)
class RunStatusView:
    """一次运行状态卡的不可变视图。刻意不含 percent：无真实百分比。"""

    state: str
    operation_id: str
    elapsed_seconds: int
    last_activity_seconds: int | None
    step_index: int
    text: str

    def __post_init__(self):
        if self.state not in RUN_STATES:
            raise ValueError(f'非法运行状态: {self.state}')
        if not 0 <= self.step_index < len(RUN_STEPS):
            raise ValueError(f'非法步骤序号: {self.step_index}')


def derive_run_state(phase: str, *, operation_status: str | None = None,
                     stop_requested: bool = False) -> str:
    """从真实相位/durable operation 状态推导 UI 状态。

    优先级：终态原样 > unknown 如实 > 停止中 > 等待用户 > 运行/排队。
    """
    if phase in _TERMINAL_PHASES:
        return phase
    if operation_status == 'unknown':
        return 'unknown'
    if stop_requested and phase == 'running':
        return 'stopping'
    if operation_status in _WAITING_OPERATION_STATUSES:
        return 'waiting_user'
    if phase in RUN_STATES:
        return phase
    return 'unknown'


def derive_step(*, accepted: bool, has_output: bool, tools_running: int,
                finishing: bool = False) -> int:
    """从真实进度信号推导当前步骤（无伪造百分比）。"""
    if finishing:
        return 3
    if tools_running > 0:
        return 2
    if accepted:
        return 1
    return 0


def format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f'{hours}:{minutes:02d}:{secs:02d}'
    return f'{minutes:02d}:{secs:02d}'


def format_last_activity(seconds: float | None) -> str:
    if seconds is None:
        return '暂无活动记录'
    value = max(0, int(seconds))
    if value < 3:
        return '刚刚'
    if value < 60:
        return f'{value} 秒前'
    return f'{value // 60} 分钟前'


def _stepper_html(step_index: int) -> str:
    parts = []
    for index, label in enumerate(RUN_STEPS):
        mark = '●' if index == step_index else ('✓' if index < step_index else '○')
        color = RUNNING if index == step_index else (
            SUCCESS if index < step_index else MUTED)
        parts.append(f'<span style="color:{color}">{mark} {label}</span>')
    return '<span style="color:#c9cdd6"> ─ </span>'.join(parts)


def _meta_html(view: RunStatusView) -> str:
    short_id = html.escape(view.operation_id[:9])
    bits = [f'任务 {short_id}', f'用时 {format_duration(view.elapsed_seconds)}']
    if view.state not in _TERMINAL_PHASES:
        bits.append(f'最后活动 {format_last_activity(view.last_activity_seconds)}')
    return (f'<span style="color:{LOG};font-size:10px"> · '
            + ' · '.join(bits) + '</span>')


def status_card_html(view: RunStatusView) -> str:
    """运行中/等待确认/正在停止的实时状态卡（QTextBrowser 子集 HTML）。"""
    label = RUN_STATE_LABELS[view.state]
    color = _STATE_COLORS[view.state]
    text = html.escape(view.text).replace('\n', '<br>')
    body = f'<p style="font-size:14px;line-height:170%">{text}</p>' if text else ''
    return (
        f'<table width="100%" cellpadding="12"><tr><td bgcolor="{CARD_BG_STATUS}">'
        f'<span style="color:{color};font-size:11px">● {label}</span>'
        + _meta_html(view) + '<br>'
        f'<span style="font-size:10px">{_stepper_html(view.step_index)}</span>'
        + body +
        '</td></tr></table><p style="font-size:8px">&nbsp;</p>'
    )


def terminal_line_html(view: RunStatusView) -> str:
    """终态摘要行：临时状态卡被终态替换后的单行记录。"""
    label = RUN_STATE_LABELS[view.state]
    color = _STATE_COLORS[view.state]
    mark = {'completed': '✓', 'failed': '✕', 'cancelled': '■',
            'unknown': '?'}.get(view.state, '●')
    return (
        f'<p style="color:{color};font-size:11px">{mark} {label}'
        f'<span style="color:{LOG};font-size:10px"> · '
        f'任务 {html.escape(view.operation_id[:9])} · '
        f'用时 {format_duration(view.elapsed_seconds)}</span></p>'
    )
