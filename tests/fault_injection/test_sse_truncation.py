"""S8-04 故障注入：SSE 流截断。

注入：上游流在未发 [DONE] 的情况下结束（网络中途断开）→
必须抛 provider_stream_incomplete，且不得产出 message_complete /
tool_call_complete 事件（不完整的工具参数不得当作完整结果下发）。
"""
from __future__ import annotations

from asset_based_agent.report_review_server.services.provider_gateway import (
    ProviderCallError,
    iter_openai_stream_events,
)


def _collect_until_failure(lines):
    """逐条消费流事件，返回 (异常前已产出的事件, 捕获的异常)。"""
    events = []
    iterator = iter_openai_stream_events(iter(lines))
    failure = None
    try:
        while True:
            events.append(next(iterator))
    except StopIteration:
        pass
    except ProviderCallError as exc:
        failure = exc
    return events, failure


def test_sse_truncation_without_done_rejected():
    lines = [(
        'data: {"choices": [{"delta": {"content": "部分回复"}, '
        '"finish_reason": null}]}'
    )]
    # 流在此被截断：没有 [DONE]，也没有 finish_reason
    events, failure = _collect_until_failure(lines)
    assert failure is not None
    assert failure.code == 'provider_stream_incomplete'
    kinds = [event['kind'] for event in events]
    assert 'message_complete' not in kinds


def test_sse_truncation_mid_tool_call_never_yields_complete():
    lines = [(
        'data: {"choices": [{"delta": {"tool_calls": [{"index": 0, '
        '"id": "call-1", "function": {"name": "read_file", '
        '"arguments": "{\\"path\\":"}}]}}]}'
    )]
    # arguments JSON 尚未闭合即断流
    events, failure = _collect_until_failure(lines)
    assert failure is not None
    assert failure.code == 'provider_stream_incomplete'
    kinds = [event['kind'] for event in events]
    assert 'tool_call_complete' not in kinds, '截断的工具调用不得下发 complete'
    assert 'message_complete' not in kinds
