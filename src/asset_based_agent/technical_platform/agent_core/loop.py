"""Agent loop: model → tools → results → model（S05 完整版）。

强制不变量：
- 每个 ToolCall 必有 ToolResult；
- Assistant 最终 Entry 不含未闭合 ToolCall；
- Operation 终态后任何迟到事件不得改变树（late-result barrier）；
- 失败和取消也提交用户可见错误 Entry；
- 所有流式 await 点与取消令牌竞速，abort 不会死锁。
"""
import asyncio
import json
from hashlib import sha256

from .contracts import ToolResult
from .errors import (
    AgentCancelled,
    AgentError,
    ContextOverflow,
    ModelProtocolError,
    ToolFailed,
    ToolInvalidArguments,
)
from .fakes import OPEN_STATUSES

MAX_TURNS = 8
PARALLEL_SAFE_RISKS = frozenset({'local_readonly'})


def _validate_arguments(descriptor, arguments):
    if not isinstance(arguments, dict):
        raise ToolInvalidArguments('工具参数必须是对象')
    missing = [key for key in descriptor.input_schema.get('required', ())
               if key not in arguments]
    if missing:
        raise ToolInvalidArguments(f'工具参数缺失: {", ".join(missing)}')


async def _race_cancel(coro_or_future, cancel):
    """让一个 await 与取消令牌竞速；取消先到则抛出 AgentCancelled。

    被抛弃的任务不强制 cancel（工具可能持有副作用），其结果由
    late-result barrier 丢弃。
    """
    task = asyncio.ensure_future(coro_or_future)
    watch = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait({task, watch},
                                     return_when=asyncio.FIRST_COMPLETED)
        if watch in done and not task.done():
            raise AgentCancelled('操作已取消')
        return await task
    finally:
        watch.cancel()
        await asyncio.gather(watch, return_exceptions=True)


async def _next_event(stream_iter, cancel):
    try:
        return await _race_cancel(stream_iter.__anext__(), cancel)
    except StopAsyncIteration:
        return None


def _is_open(repo, operation_id):
    return repo.get_operation(operation_id).status in OPEN_STATUSES


def _context_sha256(request):
    canonical = json.dumps(
        [{'role': m['role'], 'payload': m['payload']} for m in request.messages],
        ensure_ascii=False, sort_keys=True)
    return sha256(canonical.encode('utf-8')).hexdigest()


class _ToolCallAccumulator:
    """拼装 tool_call_delta 参数增量，直到 tool_call_complete。"""

    def __init__(self):
        self._partials = {}

    def feed_delta(self, data):
        call_id = data.get('id') or 'default'
        partial = self._partials.setdefault(
            call_id, {'id': call_id, 'name': data.get('name', ''),
                      'fragments': []})
        if data.get('name'):
            partial['name'] = data['name']
        fragment = data.get('arguments_fragment')
        if fragment:
            partial['fragments'].append(fragment)

    def finalize(self, data):
        call_id = data.get('id') or 'default'
        partial = self._partials.pop(call_id, None)
        if 'arguments' in data:
            arguments = data['arguments']
        elif partial is not None and partial['fragments']:
            try:
                arguments = json.loads(''.join(partial['fragments']))
            except (TypeError, ValueError):
                arguments = None  # 坏 JSON → tool.invalid_arguments
        else:
            arguments = {}
        name = data.get('name') or (partial['name'] if partial else '')
        return {'id': call_id, 'name': name, 'arguments': arguments}

    def discard_all(self):
        self._partials.clear()


async def run_agent_loop(*, repo, model, tools, operation, cancel, emit,
                         steer_queue=None, max_turns=MAX_TURNS,
                         policy=None, approver=None, file_scope=None,
                         context_builder=None):
    """驱动单个 operation 直到完成/失败/取消；所有结果写回 repo。"""
    emit('operation_started')
    tools_by_name = {tool.descriptor.name: tool for tool in tools}
    for ordinal in range(1, max_turns + 1):
        if not _is_open(repo, operation.id):
            return 'aborted'
        _drain_steer(repo, operation, steer_queue, emit)
        request = repo.build_model_request(operation)
        if context_builder is not None:
            from dataclasses import replace
            built = context_builder.build(repo=repo, operation=operation,
                                          tools=tools)
            request = replace(request, messages=built.messages)
        turn_id = repo.begin_turn(
            operation.id, ordinal,
            input_context_sha256=_context_sha256(request),
            model_request_id=request.request_id)
        emit('turn_started', turn_id=turn_id, payload={'ordinal': ordinal})
        try:
            outcome = await _run_turn(
                repo=repo, model=model, tools_by_name=tools_by_name,
                operation=operation, turn_id=turn_id, request=request,
                cancel=cancel, emit=emit, policy=policy, approver=approver,
                file_scope=file_scope)
        except AgentCancelled:
            repo.finish_turn(turn_id, 'aborted',
                             error_code='agent.cancelled')
            repo.abort_operation(operation.id, turn_id=turn_id)
            emit('turn_failed', turn_id=turn_id,
                 payload={'error_code': AgentCancelled.code})
            emit('operation_aborted', turn_id=turn_id)
            return 'aborted'
        except AgentError as exc:
            repo.finish_turn(turn_id, 'failed', error_code=exc.code)
            repo.fail_operation(operation.id, code=exc.code, summary=str(exc),
                                turn_id=turn_id)
            emit('turn_failed', turn_id=turn_id, payload={'error_code': exc.code})
            emit('operation_failed', turn_id=turn_id,
                 payload={'error_code': exc.code})
            return 'failed'
        if outcome == 'completed':
            return 'completed'
    repo.fail_operation(operation.id, code=ContextOverflow.code,
                        summary=f'超过最大轮次 {max_turns}', turn_id=None)
    emit('operation_failed', payload={'error_code': ContextOverflow.code})
    return 'failed'


def _drain_steer(repo, operation, steer_queue, emit):
    """turn 边界注入用户 steer 消息（持久化后进入下一次模型请求）。"""
    if not steer_queue:
        return
    while steer_queue:
        text = steer_queue.popleft()
        entry = repo.append_entry(
            operation.session_id, operation.lane_id, 'user_message',
            {'text': text, 'steered': True}, operation_id=operation.id)
        emit('message_committed',
             payload={'entry_id': entry.id, 'role': 'user', 'steered': True})


async def _run_turn(*, repo, model, tools_by_name, operation, turn_id,
                    request, cancel, emit, policy=None, approver=None,
                    file_scope=None):
    """单个 turn：模型流 → （可选）工具批次 →  continuation 或 final。"""
    text_parts = []
    accumulator = _ToolCallAccumulator()
    tool_calls = []
    usage = {}
    emit('model_request_started', turn_id=turn_id)
    stream_iter = model.stream(request, cancel)
    while True:
        event = await _next_event(stream_iter, cancel)
        if event is None:
            break
        cancel.raise_if_cancelled()
        if event.kind == 'text_delta':
            text_parts.append(event.data['text'])
            emit('message_delta', turn_id=turn_id,
                 payload={'text': event.data['text']})
        elif event.kind == 'tool_call_delta':
            accumulator.feed_delta(event.data)
        elif event.kind == 'tool_call_complete':
            tool_calls.append(accumulator.finalize(event.data))
        elif event.kind == 'usage':
            usage = dict(event.data)
        elif event.kind == 'request_failed':
            raise ModelProtocolError(
                event.data.get('error', '模型请求失败'))
    cancel.raise_if_cancelled()
    if not tool_calls:
        entry = repo.append_entry(
            operation.session_id, operation.lane_id, 'assistant_message',
            {'text': ''.join(text_parts)},
            operation_id=operation.id, turn_id=turn_id)
        emit('message_committed', turn_id=turn_id,
             payload={'entry_id': entry.id})
        repo.finish_turn(turn_id, 'completed', assistant_entry_id=entry.id,
                         usage=usage)
        emit('turn_completed', turn_id=turn_id)
        repo.complete_operation(operation.id, assistant_entry_id=entry.id,
                                turn_id=turn_id)
        emit('operation_completed')
        return 'completed'
    # 中间 turn 的 assistant 文本同样落树（不含未闭合 ToolCall：调用以
    # 独立 tool_call Entry 表达，最终 assistant Entry 只在无调用时提交）。
    if ''.join(text_parts).strip():
        repo.append_entry(
            operation.session_id, operation.lane_id, 'assistant_message',
            {'text': ''.join(text_parts), 'intermediate': True},
            operation_id=operation.id, turn_id=turn_id)
    await _execute_tool_batch(
        repo=repo, tools_by_name=tools_by_name, operation=operation,
        turn_id=turn_id, calls=tool_calls, cancel=cancel, emit=emit,
        policy=policy, approver=approver, file_scope=file_scope)
    repo.finish_turn(turn_id, 'completed', usage=usage)
    emit('turn_completed', turn_id=turn_id)
    return 'continued'


async def _execute_tool_batch(*, repo, tools_by_name, operation, turn_id,
                              calls, cancel, emit, policy=None, approver=None,
                              file_scope=None):
    """工具批次：tool_call 先按序落树；安全工具并行，其余串行；
    ToolResult 按调用顺序落树；每个 ToolCall 必有 ToolResult。"""
    records = []
    for index, call in enumerate(calls):
        entry = repo.append_entry(
            operation.session_id, operation.lane_id, 'tool_call',
            {'id': call['id'], 'name': call['name'],
             'arguments': call['arguments']},
            operation_id=operation.id, turn_id=turn_id)
        tool = tools_by_name.get(call['name'])
        risk = tool.descriptor.risk if tool is not None else 'process'
        record_id = repo.begin_tool_call(
            operation.id, turn_id, name=call['name'],
            arguments=call['arguments'] if isinstance(call['arguments'], dict)
            else {}, risk=risk,
            idempotency_key=f'{turn_id}:{call["id"]}')
        records.append({'call': call, 'tool': tool, 'entry': entry,
                        'record_id': record_id, 'index': index})
        emit('tool_proposed', turn_id=turn_id, tool_call_id=entry.id,
             payload={'name': call['name']})

    results = {}

    async def run_one(record):
        tool = record['tool']
        try:
            if tool is None:
                raise ToolInvalidArguments(f"未注册的工具: {record['call']['name']}")
            _validate_arguments(tool.descriptor, record['call']['arguments'])
            if policy is not None:
                denied = await _enforce_policy(
                    record=record, repo=repo, policy=policy, approver=approver,
                    operation=operation, file_scope=file_scope,
                    turn_id=turn_id, emit=emit)
                if denied is not None:
                    results[record['index']] = denied
                    return
            emit('tool_started', turn_id=turn_id,
                 tool_call_id=record['entry'].id,
                 payload={'name': record['call']['name']})
            result = await _race_cancel(
                tool.execute(None, record['call']['arguments'], cancel), cancel)
            if not isinstance(result, ToolResult):
                raise ToolFailed('工具返回值不符合 ToolResult 契约')
            results[record['index']] = result
        except AgentCancelled:
            raise
        except AgentError as exc:
            results[record['index']] = ToolResult(
                status='failed', error_code=exc.code, content=str(exc))
        except Exception:  # noqa: BLE001 - 工具异常必须归类，不得穿透
            results[record['index']] = ToolResult(
                status='failed', error_code=ToolFailed.code,
                content='工具执行失败')

    safe = [r for r in records
            if r['tool'] is not None
            and r['tool'].descriptor.risk in PARALLEL_SAFE_RISKS]
    safe_ids = {id(r) for r in safe}
    unsafe = [r for r in records if id(r) not in safe_ids]
    await asyncio.gather(*(run_one(record) for record in safe))
    for record in unsafe:
        await run_one(record)
    if not _is_open(repo, operation.id):
        return  # late-result barrier：operation 已被 abort，结果不落树
    for record in records:
        result = results[record['index']]
        result_entry = repo.append_entry(
            operation.session_id, operation.lane_id, 'tool_result',
            {'tool_call_id': record['call']['id'],
             'name': record['call']['name'], 'status': result.status,
             'result': result.result, 'content': result.content,
             'error_code': result.error_code},
            operation_id=operation.id, turn_id=turn_id)
        repo.finish_tool_call(
            record['record_id'],
            'succeeded' if result.status == 'succeeded' else 'failed',
            result_entry_id=result_entry.id,
            error_code=result.error_code or None)
        emit('tool_completed' if result.status == 'succeeded' else 'tool_failed',
             turn_id=turn_id, tool_call_id=record['entry'].id,
             payload={'name': record['call']['name'],
                      'status': result.status,
                      'error_code': result.error_code})


async def _enforce_policy(*, record, repo, policy, approver, operation,
                          file_scope, turn_id, emit):
    """统一权限闸门：无 PolicyDecision 不执行；决定与 receipt 全部由引擎产生。

    返回 None 表示放行（receipt 已签发并登记）；否则返回拒绝用 ToolResult。
    """
    from ..policies.contracts import ApprovalRequest, Principal

    receipts = policy.receipts
    session_id, operation_id = operation.session_id, operation.id

    def denied(reason):
        return ToolResult(status='failed', error_code='tool.permission_denied',
                          content=reason)

    # 用户撤销立即阻止未开始的 ToolCall
    if receipts.is_revoked(session_id, operation_id):
        return denied('授权已被用户撤销，未开始的操作已阻止')
    tool = record['tool']
    call = record['call']
    arguments = call['arguments'] if isinstance(call['arguments'], dict) else {}
    # 权限模式按调用实时读取：切换只影响后续 ToolCall，不追溯扩大旧授权
    mode = repo.session_permission_mode(session_id)
    principal = Principal(session_id=session_id, operation_id=operation_id)
    decision = policy.evaluate(principal, mode, tool.descriptor,
                               dict(arguments), file_scope)
    if decision.kind == 'deny':
        return denied(f'权限策略拒绝：{decision.reason}')
    if decision.kind == 'ask':
        approved = False
        if approver is not None:
            approved = await approver.approve(ApprovalRequest(
                principal=principal, mode=mode, tool=tool.descriptor,
                arguments=dict(arguments), reason=decision.reason,
                grants=tuple(decision.grants)))
        if not approved:
            return denied('该操作需要用户批准，本次未获批准')
        if receipts.is_revoked(session_id, operation_id):
            return denied('授权已被用户撤销，未开始的操作已阻止')
    canonical = json.dumps(arguments, ensure_ascii=False, sort_keys=True)
    receipt = receipts.issue(
        session_id=session_id, operation_id=operation_id,
        tool_call_id=record['record_id'], tool_name=call['name'],
        arguments_sha256=sha256(canonical.encode('utf-8')).hexdigest(),
        grants=tuple(decision.grants), restrictions=dict(decision.restrictions))
    repo.set_tool_call_authorization(record['record_id'], receipt.receipt_id)
    # 模型文本中的 permission_receipt 不可信：一律以引擎签发的授予覆盖
    if 'permission_receipt' in arguments:
        call['arguments'] = {
            **arguments,
            'permission_receipt': {'receipt_id': receipt.receipt_id,
                                   'granted': sorted(receipt.grants),
                                   'issued_by': 'policy_engine'}}
    emit('tool_authorized', turn_id=turn_id, tool_call_id=record['entry'].id,
         payload={'name': call['name'], 'decision': decision.kind,
                  'receipt_id': receipt.receipt_id})
    return None
