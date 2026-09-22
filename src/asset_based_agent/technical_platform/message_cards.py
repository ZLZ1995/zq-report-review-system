"""S10 消息层级卡片构建器：User / Assistant / SystemEvent / Warning / Error。

所有文本一律 HTML 转义；ErrorCard 只暴露安全公开错误码与任务 id，
诊断信息不含 traceback、token、密钥、密码（任务书第 19 条铁律）。
"""
from __future__ import annotations

import html
from datetime import datetime, timezone

from .ui_theme import (
    CARD_BG_ERROR,
    CARD_BG_NEUTRAL,
    CARD_BG_WARNING,
    ERROR,
    ERROR_TEXT,
    LOG,
    LOG_FONT_SIZE,
    LOG_LINE_HEIGHT,
    LOG_TEXT,
    MUTED,
    USER_CARD_BG,
    WARNING,
    WARNING_TEXT,
)

_GAP = '<p style="font-size:8px">&nbsp;</p>'


def _escape(text: str) -> str:
    return html.escape(str(text)).replace('\n', '<br>')


def user_card_html(text: str, *, live: bool = False) -> str:
    """UserMessageCard：用户消息（live=True 为发送中）。"""
    label = '你 · 发送中' if live else '你'
    return (
        '<table width="100%" cellspacing="0" cellpadding="16">'
        f'<tr><td width="12%"></td><td bgcolor="{USER_CARD_BG}">'
        f'<span style="color:{LOG};font-size:11px">{label}</span>'
        f'<p style="line-height:160%;font-size:14px">{_escape(text)}</p>'
        '</td></tr></table>' + _GAP
    )


def assistant_card_html(text: str) -> str:
    """AssistantMessageCard：助手正式回复。"""
    return (
        '<p style="font-size:13px;color:#3e4c66"><b>ZQ</b>'
        f' <span style="font-size:10px;color:{MUTED}"> / ASSISTANT</span></p>'
        f'<p style="font-size:14px;line-height:170%;margin-bottom:28px">'
        f'{_escape(text)}</p>'
    )


def system_event_card_html(text: str) -> str:
    """SystemEventCard：中性系统事件（执行记录单条）。"""
    return (
        '<table width="100%" cellpadding="12"><tr>'
        f'<td bgcolor="{CARD_BG_NEUTRAL}"><span style="color:{LOG};font-size:{LOG_FONT_SIZE}px">'
        '●  执行记录</span>'
        f'<p style="color:{LOG_TEXT};font-size:{LOG_FONT_SIZE}px;line-height:{LOG_LINE_HEIGHT}%">'
        f'{_escape(text)}</p>'
        '</td></tr></table>' + _GAP
    )


def warning_card_html(text: str) -> str:
    """WarningCard：需要用户注意但不阻断的告警。"""
    return (
        '<table width="100%" cellpadding="12"><tr>'
        f'<td bgcolor="{CARD_BG_WARNING}"><span style="color:{WARNING};font-size:11px">'
        '▲  警告</span>'
        f'<p style="color:{WARNING_TEXT};font-size:12px;line-height:150%">'
        f'{_escape(text)}</p>'
        '</td></tr></table>' + _GAP
    )


def error_card_html(text: str, *, error_code: str = '',
                    operation_id: str = '') -> str:
    """ErrorCard + Error detail + diagnostics copy 入口。

    只显示安全公开错误码与任务 id；诊断细节通过 zq-diagnostics 锚点复制。
    """
    detail = ''
    if error_code or operation_id:
        chip = f'错误码 {html.escape(error_code)}' if error_code else ''
        task = (f'任务 {html.escape(operation_id[:9])}'
                if operation_id else '')
        sep = ' · ' if chip and task else ''
        link = ''
        if operation_id:
            link = (f'　<a href="zq-diagnostics:{operation_id}'
                    f'/{html.escape(error_code)}">复制诊断信息</a>')
        detail = (f'<p style="color:{MUTED};font-size:10px">{chip}{sep}{task}'
                  f'{link}</p>')
    return (
        '<table width="100%" cellpadding="12"><tr>'
        f'<td bgcolor="{CARD_BG_ERROR}"><span style="color:{ERROR};font-size:11px">'
        '✕  失败</span>'
        f'<p style="color:{ERROR_TEXT};font-size:12px;line-height:150%">'
        f'{_escape(text)}</p>'
        + detail +
        '</td></tr></table>' + _GAP
    )


def diagnostics_text(*, operation_id: str, error_code: str, summary: str,
                     client_version: str) -> str:
    """可复制诊断信息：仅公开字段，绝不包含 traceback/凭据/密钥。"""
    lines = [
        'ZQ Workspace 诊断信息',
        f'时间: {datetime.now(tz=timezone.utc).isoformat(timespec="seconds")}',
        f'客户端版本: {client_version}',
        f'任务 ID: {operation_id}',
        f'错误码: {error_code or "未提供"}',
        f'用户可见摘要: {summary}',
    ]
    return '\n'.join(lines)


def execution_group_html(events: list[str], *, group_id: str,
                         collapsed: bool) -> str:
    """执行记录折叠卡：折叠态显示条数+最近一条，展开态显示全部。"""
    safe_id = html.escape(group_id)
    if collapsed:
        latest = _escape(events[-1]) if events else ''
        return (
            '<table width="100%" cellpadding="12"><tr>'
            f'<td bgcolor="{CARD_BG_NEUTRAL}"><span style="color:{LOG};font-size:{LOG_FONT_SIZE}px">'
            f'●  执行记录（{len(events)} 条）</span>'
            f'<p style="color:{LOG_TEXT};font-size:{LOG_FONT_SIZE}px;line-height:{LOG_LINE_HEIGHT}%">'
            f'最近：{latest}　'
            f'<a href="zq-events:{safe_id}">展开全部</a></p>'
            '</td></tr></table>' + _GAP
        )
    rows = ''.join(
        f'<p style="color:{LOG_TEXT};font-size:{LOG_FONT_SIZE}px;line-height:{LOG_LINE_HEIGHT}%">'
        f'{_escape(event)}</p>'
        for event in events)
    return (
        '<table width="100%" cellpadding="12"><tr>'
        f'<td bgcolor="{CARD_BG_NEUTRAL}"><span style="color:{LOG};font-size:{LOG_FONT_SIZE}px">'
        f'●  执行记录（{len(events)} 条）</span>'
        + rows
        + f'<p style="font-size:{LOG_FONT_SIZE}px"><a href="zq-events:{safe_id}">收起</a></p>'
        '</td></tr></table>' + _GAP
    )
