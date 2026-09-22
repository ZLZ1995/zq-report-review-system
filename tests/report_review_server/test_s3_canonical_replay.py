"""S3-02 canonical replay payload：>5000 delta 长流可完整幂等重放（先红后绿）。

旧实现保存原始流事件并在 2000 条处截断；新实现保存 canonical replay
payload，重放时重新编码 SSE，正文与首次完全一致。
"""
from __future__ import annotations

import json

from sqlalchemy import select

from asset_based_agent.report_review_server.models import (
    BillingRequest,
    WalletLedger,
)

from .test_agent_completion_stream import (
    _admin_and_user,
    _collect,
    _db,
    _install_provider,
    _setup_billable,
    _stream,
)


def _long_script(chunks: int = 6000):
    script = [{'kind': 'message_start', 'data': {}}]
    script += [{'kind': 'text_delta', 'data': {'text': f'片段{i:05d} '}}
               for i in range(chunks)]
    script.append({'kind': 'usage', 'data': {'input_tokens': 100,
                                             'output_tokens': 6000}})
    script.append({'kind': 'message_complete',
                   'data': {'finish_reason': 'stop'}})
    return script


def test_long_stream_replays_completely_without_double_charge(client):
    """>5000 text delta 长流：首次成功，同 request id 重放正文完全一致。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    fake = _install_provider(client, [_long_script()])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-long-1') as first:
        first_events = _collect(first)
    assert len(first_events) > 5000
    with _stream(client, token, model['model_id'], 'req-long-1') as second:
        second_events = _collect(second)
    assert len(fake.payloads) == 1, '重放不得再次调用 provider'
    assert [k for k, _ in second_events] == [k for k, _ in first_events], \
        '重放事件序列必须与首次完全一致（不得截断）'
    first_text = ''.join(
        d.get('text', '') for k, d in first_events if k == 'text_delta')
    second_text = ''.join(
        d.get('text', '') for k, d in second_events if k == 'text_delta')
    assert second_text == first_text and len(second_text) > 5000
    for events in (first_events, second_events):
        kinds = [k for k, _ in events]
        assert 'usage' in kinds, 'usage 必须存在'
        assert 'message_complete' in kinds, 'message_complete 必须存在'
        assert events[-1][0] == 'receipt', 'receipt 必须存在'
    assert second_events[-1][1]['replayed'] is True
    assert second_events[-1][1]['charged_amount'] == \
        first_events[-1][1]['charged_amount']
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-long-1'))
        charges = list(db.scalars(select(WalletLedger).where(
            WalletLedger.reference_id == billing.billing_request_id)))
        assert len(charges) == 1, '重放不得重复扣费'


def test_stored_replay_payload_is_canonical(client):
    """存储的是 canonical replay payload 而不是被截断的原始事件数组。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    script = [
        {'kind': 'message_start', 'data': {}},
        {'kind': 'text_delta', 'data': {'text': '完整回答'}},
        {'kind': 'usage', 'data': {'input_tokens': 10, 'output_tokens': 5}},
        {'kind': 'message_complete', 'data': {'finish_reason': 'stop'}},
    ]
    _install_provider(client, [script])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-canonical-1') as resp:
        _collect(resp)
    with _db(client) as db:
        billing = db.scalar(select(BillingRequest).where(
            BillingRequest.client_request_id == 'req-canonical-1'))
        cipher = client.app.state.review_job_service.metered.cipher
        payload = json.loads(cipher.decrypt(
            billing.response_ciphertext,
            purpose=f'billing-response:{billing.billing_request_id}'))
    assert isinstance(payload, dict), '必须保存 canonical payload 对象'
    assert payload['message_complete'] is True
    assert payload['assistant_text'] == '完整回答'
    assert payload['usage']['input_tokens'] == 10
    assert payload['finish_reason'] == 'stop'


def test_tool_call_stream_replays_identically(client):
    """含工具调用的流：重放事件逐项等于首次（除 receipt.replayed 标记）。"""
    admin, user = _admin_and_user(client)
    model = _setup_billable(client, admin, user)
    script = [
        {'kind': 'message_start', 'data': {}},
        {'kind': 'tool_call_delta', 'data': {
            'index': 0, 'name': 'calc', 'arguments_fragment': '{"x"'}},
        {'kind': 'tool_call_delta', 'data': {
            'index': 0, 'name': 'calc', 'arguments_fragment': ': 2}'}},
        {'kind': 'tool_call_complete', 'data': {
            'id': 'call-0', 'name': 'calc', 'arguments': {'x': 2}}},
        {'kind': 'usage', 'data': {'input_tokens': 12, 'output_tokens': 7}},
        {'kind': 'message_complete', 'data': {'finish_reason': 'tool_calls'}},
    ]
    _install_provider(client, [script])
    token = str(user['access_token'])
    with _stream(client, token, model['model_id'], 'req-tool-1') as first:
        first_events = _collect(first)
    with _stream(client, token, model['model_id'], 'req-tool-1') as second:
        second_events = _collect(second)
    assert second_events[:-1] == first_events[:-1], \
        '重放的非 receipt 事件必须与首次逐项一致'
    assert second_events[-1][1]['replayed'] is True
