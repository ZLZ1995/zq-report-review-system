"""S2-03 客户端对账：stale（unknown）operation 按服务端真实状态收束。

映射规则（总任务书 S2-03）：
- succeeded → replay（回放事件落本地树，operation completed）
- failed → 本地 fail（沿用服务端 error_code）
- streaming + live lease → 保持 busy（不动）
- uncertain/disconnected → reconciliation_required（绝不自动重放/改写 failed）
- 不存在 → 本地 fail

query/replay 为注入的可调用对象，由网关绑定到 ServerModelPort：
- query(client_request_id) -> dict | None（None 表示服务端无此请求）
- replay(client_request_id) -> Iterable[dict]（仅 succeeded 时调用）
"""
import logging

logger = logging.getLogger(__name__)


def _stale_turn(repo, operation_id):
    stale = [t for t in repo.turns(operation_id) if t.status == 'unknown']
    return stale[-1] if stale else None


def reconcile_unknown_operation(repo, operation_id, *, query, replay=None):
    """对账单个 unknown operation；返回收束结果标识。"""
    operation = repo.get_operation(operation_id)
    if operation.status != 'unknown':
        raise ValueError('只有中断（unknown）的 operation 需要对账')
    turn = _stale_turn(repo, operation_id)
    request_id = turn.model_request_id if turn is not None else None
    if not request_id:
        # 中断时还未发出服务端请求：副作用不存在，本地安全失败收束
        repo.fail_operation(
            operation_id, code='model.protocol_error',
            summary='中断时没有可对账的服务端请求标识', turn_id=None)
        return 'failed'
    result = query(request_id)
    if result is None:
        if turn is not None:
            repo.finish_turn(turn.id, 'failed',
                             error_code='model.protocol_error')
        repo.fail_operation(
            operation_id, code='model.protocol_error',
            summary='服务端无该请求记录，按失败收束',
            turn_id=turn.id if turn is not None else None)
        return 'failed'
    status = str(result.get('status', ''))
    if status == 'succeeded':
        if replay is None:
            logger.warning('服务端 succeeded 但无 replay 通道: %s', request_id)
            return _mark_reconciliation_required(repo, operation, turn,
                                                 result)
        text_parts = []
        for event in replay(request_id):
            if event.get('kind') == 'text_delta':
                text_parts.append(str(event.get('data', {}).get('text', '')))
        entry = repo.append_entry(
            operation.session_id, operation.lane_id, 'assistant_message',
            {'text': ''.join(text_parts), 'reconciled': True},
            operation_id=operation_id,
            turn_id=turn.id if turn is not None else None)
        if turn is not None:
            repo.finish_turn(turn.id, 'completed', assistant_entry_id=entry.id)
        repo.complete_operation(operation_id, assistant_entry_id=entry.id,
                                turn_id=turn.id if turn is not None else None)
        return 'completed'
    if status == 'failed':
        code = result.get('error_code') or 'model.protocol_error'
        if turn is not None:
            repo.finish_turn(turn.id, 'failed', error_code=code)
        repo.fail_operation(
            operation_id, code=code,
            summary='服务端请求已失败（对账收束）',
            turn_id=turn.id if turn is not None else None)
        return 'failed'
    if status == 'streaming':
        # 二次整改项2：仅当服务端证明 lease 仍活才保持 busy；
        # stale lease 的 streaming 必须进入人工对账，绝不永久 busy
        if result.get('lease_live'):
            return 'busy'
        return _mark_reconciliation_required(repo, operation, turn, result)
    # uncertain / disconnected / 其他：绝不自动重放，也不得直接改写成失败
    return _mark_reconciliation_required(repo, operation, turn, result)


def _mark_reconciliation_required(repo, operation, turn, result):
    code = result.get('error_code') or 'reconciliation_required'
    repo.append_entry(
        operation.session_id, operation.lane_id, 'error_message',
        {'text': f'本轮结果需要人工对账（{code}），未自动重放。',
         'error_code': code, 'reconciliation_required': True},
        operation_id=operation.id,
        turn_id=turn.id if turn is not None else None)
    return 'reconciliation_required'
