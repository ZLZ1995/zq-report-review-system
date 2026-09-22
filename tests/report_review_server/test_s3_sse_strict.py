"""S3-04 Provider SSE 严格协议校验：非法上游结构一律 ProviderCallError（先红后绿）。

不允许 AttributeError / TypeError / ValueError 裸穿透；只有收到可靠终止
证据（[DONE] + finish_reason）才发 message_complete。
"""
from __future__ import annotations

import pytest

from asset_based_agent.report_review_server.services.provider_gateway import (
    ProviderCallError,
    iter_openai_stream_events,
)


def _run(lines):
    return list(iter_openai_stream_events(iter(lines)))


def test_choices_as_string_rejected():
    with pytest.raises(ProviderCallError):
        _run(['data: {"choices": "oops"}', 'data: [DONE]'])


def test_choice_non_dict_rejected():
    with pytest.raises(ProviderCallError):
        _run(['data: {"choices": [42]}', 'data: [DONE]'])


def test_delta_non_dict_rejected():
    with pytest.raises(ProviderCallError):
        _run(['data: {"choices": [{"delta": "text"}]}', 'data: [DONE]'])


def test_tool_index_non_numeric_rejected():
    with pytest.raises(ProviderCallError):
        _run([('data: {"choices": [{"delta": {"tool_calls": '
               '[{"index": "zero"}]}}]}'), 'data: [DONE]'])


def test_tool_index_float_rejected():
    with pytest.raises(ProviderCallError):
        _run([('data: {"choices": [{"delta": {"tool_calls": '
               '[{"index": 1.5}]}}]}'), 'data: [DONE]'])


def test_tool_calls_non_list_rejected():
    with pytest.raises(ProviderCallError):
        _run([('data: {"choices": [{"delta": {"tool_calls": '
               '{"index": 0}}}]}'), 'data: [DONE]'])


def test_content_non_string_rejected():
    with pytest.raises(ProviderCallError):
        _run(['data: {"choices": [{"delta": {"content": 42}}]}',
              'data: [DONE]'])


def test_usage_numbers_as_strings_rejected():
    with pytest.raises(ProviderCallError) as excinfo:
        _run([('data: {"usage": {"prompt_tokens": "7", '
               '"completion_tokens": 3}, "choices": []}'), 'data: [DONE]'])
    assert excinfo.value.code == 'provider_usage_invalid'


def test_usage_non_dict_rejected():
    with pytest.raises(ProviderCallError) as excinfo:
        _run(['data: {"usage": "lots", "choices": []}', 'data: [DONE]'])
    assert excinfo.value.code == 'provider_usage_invalid'


def test_truncated_json_rejected():
    with pytest.raises(ProviderCallError) as excinfo:
        _run(['data: {"choices": ['])
    assert excinfo.value.code == 'provider_invalid_json'


def test_missing_done_marker_rejected():
    """socket 正常结束但消息未完成（无 [DONE]）：不得发 message_complete。"""
    lines = [
        'data: {"choices": [{"delta": {"content": "半截"}, "index": 0}]}',
        ('data: {"choices": [{"delta": {}, "finish_reason": "stop", '
         '"index": 0}]}'),
        ('data: {"usage": {"prompt_tokens": 3, "completion_tokens": 1, '
         '"total_tokens": 4}, "choices": []}'),
    ]
    with pytest.raises(ProviderCallError) as excinfo:
        _run(lines)
    assert excinfo.value.code == 'provider_stream_incomplete'


def test_missing_finish_reason_rejected():
    """有 [DONE] 但无 finish_reason：无可靠终止证据，不得发 message_complete。"""
    lines = [
        'data: {"choices": [{"delta": {"content": "你好"}, "index": 0}]}',
        ('data: {"usage": {"prompt_tokens": 3, "completion_tokens": 1, '
         '"total_tokens": 4}, "choices": []}'),
        'data: [DONE]',
    ]
    with pytest.raises(ProviderCallError) as excinfo:
        _run(lines)
    assert excinfo.value.code == 'provider_finish_missing'


def test_finish_reason_non_string_rejected():
    lines = [
        'data: {"choices": [{"delta": {}, "finish_reason": 7, "index": 0}]}',
        'data: [DONE]',
    ]
    with pytest.raises(ProviderCallError):
        _run(lines)


def test_valid_stream_still_parses_end_to_end():
    lines = [
        'data: {"choices": [{"delta": {"role": "assistant"}, "index": 0}]}',
        'data: {"choices": [{"delta": {"content": "你"}, "index": 0}]}',
        'data: {"choices": [{"delta": {"content": "好"}, "index": 0}]}',
        ('data: {"choices": [{"delta": {}, "finish_reason": "stop", '
         '"index": 0}]}'),
        ('data: {"usage": {"prompt_tokens": 3, "completion_tokens": 2, '
         '"total_tokens": 5}, "choices": []}'),
        'data: [DONE]',
    ]
    events = _run(lines)
    assert [event['kind'] for event in events] == [
        'message_start', 'text_delta', 'text_delta', 'usage',
        'message_complete']
    assert events[-1]['data']['finish_reason'] == 'stop'
