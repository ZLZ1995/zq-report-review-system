"""S05 行为测试：完整 Agent Loop——工具批次、steer/follow-up、late-result
barrier、崩溃恢复。

强制不变量（计划书 S05）：
- 每个 ToolCall 必有 ToolResult；
- Assistant 最终 Entry 不包含未闭合 ToolCall；
- Operation 完成后任何迟到事件不得改变树；
- 失败和取消也必须提交用户可见的错误 Entry。
"""
import asyncio
import time


def run(coro):
    return asyncio.run(coro)


def make_kernel(*, scripts=(), tools=(), stream_factory=None, repo=None):
    from asset_based_agent.technical_platform.agent_core.fakes import (
        FakeModelPort,
        InMemorySessionRepo,
    )
    from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
    repo = repo or InMemorySessionRepo()
    if stream_factory is not None:
        model = FakeModelPort.from_stream_factory(stream_factory)
    else:
        model = FakeModelPort(list(scripts))
    kernel = AgentKernel(repo=repo, model=model, tools=list(tools))
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return kernel, repo, model


def text_turn(text):
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
    )
    return [ModelEvent('message_start', {}),
            ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


def tool_turn(*calls):
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
    )
    return [ModelEvent('message_start', {})] + [
        ModelEvent('tool_call_complete', {
            'id': c.get('id', f'call-{i}'), 'name': c['name'],
            'arguments': c.get('arguments', {})})
        for i, c in enumerate(calls)] + [ModelEvent('message_complete', {})]


def entries(repo, lane='main'):
    return repo.entries('s1', lane)


def assert_tool_call_result_pairing(repo):
    """每个 ToolCall 必有 ToolResult，且最终 Assistant Entry 不含未闭合调用。"""
    by_type = [(e.entry_type, e.payload) for e in entries(repo)]
    call_ids = [p['id'] for t, p in by_type if t == 'tool_call']
    result_ids = [p['tool_call_id'] for t, p in by_type if t == 'tool_result']
    assert sorted(result_ids) == sorted(call_ids), '每个 ToolCall 必有 ToolResult'
    final = [p for t, p in by_type if t == 'assistant_message'][-1]
    assert 'tool_calls' not in final and 'text' in final


# ------------------------------------------------------------------ 基础链路

def test_pure_chat_commits_assistant_and_turn_row():
    kernel, repo, _ = make_kernel(scripts=[text_turn('你好')])
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    record = repo.get_operation(accepted.operation_id)
    assert record.status == 'completed'
    assert [e.entry_type for e in entries(repo)] == [
        'user_message', 'assistant_message']
    turns = repo.turns(accepted.operation_id)
    assert len(turns) == 1 and turns[0].status == 'completed'
    assert turns[0].assistant_entry_id == entries(repo)[-1].id


def test_single_tool_call_full_cycle():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('calc', handler=lambda args: args['x'] * 2)
    kernel, repo, _ = make_kernel(
        scripts=[tool_turn({'name': 'calc', 'arguments': {'x': 21}}),
                 text_turn('答案 42')],
        tools=[tool])
    accepted = run(kernel.submit('s1', 'main', {'text': '算'}))
    assert [e.entry_type for e in entries(repo)] == [
        'user_message', 'tool_call', 'tool_result', 'assistant_message']
    calls = repo.tool_calls(accepted.operation_id)
    assert calls[0].status == 'succeeded'
    assert entries(repo)[2].payload['result'] == 42
    assert_tool_call_result_pairing(repo)


def test_multiple_tool_calls_across_turns():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('step', handler=lambda args: args['n'])
    kernel, repo, _ = make_kernel(
        scripts=[tool_turn({'name': 'step', 'arguments': {'n': 1}}),
                 tool_turn({'name': 'step', 'arguments': {'n': 2}}),
                 text_turn('完成')],
        tools=[tool])
    accepted = run(kernel.submit('s1', 'main', {'text': '走两步'}))
    turns = repo.turns(accepted.operation_id)
    assert len(turns) == 3
    assert_tool_call_result_pairing(repo)


# ------------------------------------------------------------------ 工具批次

def test_parallel_safe_tool_batch_overlaps_and_keeps_order():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolResult,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    stamps = {}

    class SlowTool(FakeTool):
        async def execute(self, context, arguments, cancel):
            stamps[f'{arguments["tag"]}-start'] = time.monotonic()
            await asyncio.sleep(0.2)
            stamps[f'{arguments["tag"]}-end'] = time.monotonic()
            return ToolResult(status='succeeded', result=arguments['tag'],
                              content='ok')

    kernel, repo, _ = make_kernel(
        scripts=[tool_turn({'id': 'c1', 'name': 'slow', 'arguments': {'tag': 'a'}},
                           {'id': 'c2', 'name': 'slow', 'arguments': {'tag': 'b'}}),
                 text_turn('批完成')],
        tools=[SlowTool('slow', handler=lambda a: a)])
    run(kernel.submit('s1', 'main', {'text': '并行'}))
    assert stamps['b-start'] < stamps['a-end'], '安全工具必须并行执行'
    results = [e.payload for e in entries(repo) if e.entry_type == 'tool_result']
    assert [r['tool_call_id'] for r in results] == ['c1', 'c2'], '结果按调用顺序落树'


def test_unsafe_tool_runs_sequentially_after_safe_batch():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolResult,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    stamps = {}

    class StampTool(FakeTool):
        async def execute(self, context, arguments, cancel):
            stamps[f'{arguments["tag"]}-start'] = time.monotonic()
            await asyncio.sleep(0.1)
            stamps[f'{arguments["tag"]}-end'] = time.monotonic()
            return ToolResult(status='succeeded', result=1, content='ok')

    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolDescriptor,
    )

    class UnsafeTool(StampTool):
        pass

    safe = StampTool('safe', handler=lambda a: a)
    unsafe = StampTool('writer', handler=lambda a: a)
    unsafe.descriptor = ToolDescriptor(
        name='writer', description='w', input_schema={}, risk='local_create')
    kernel, _repo, _ = make_kernel(
        scripts=[tool_turn({'id': 'c1', 'name': 'safe', 'arguments': {'tag': 's'}},
                           {'id': 'c2', 'name': 'writer',
                            'arguments': {'tag': 'w'}}),
                 text_turn('done')],
        tools=[safe, unsafe])
    run(kernel.submit('s1', 'main', {'text': '混合'}))
    assert stamps['w-start'] >= stamps['s-end'], '非只读工具不得与安全批次并行'


def test_tool_failure_produces_result_and_loop_continues():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool

    def boom(arguments):
        raise RuntimeError('磁盘错误')

    kernel, repo, _ = make_kernel(
        scripts=[tool_turn({'name': 'fragile', 'arguments': {}}),
                 text_turn('工具失败但已恢复')],
        tools=[FakeTool('fragile', handler=boom)])
    accepted = run(kernel.submit('s1', 'main', {'text': '试'}))
    calls = repo.tool_calls(accepted.operation_id)
    assert calls[0].status == 'failed'
    assert calls[0].error_code == 'tool.failed'
    result = next(e for e in entries(repo) if e.entry_type == 'tool_result')
    assert result.payload['status'] == 'failed'
    assert repo.get_operation(accepted.operation_id).status == 'completed'
    assert_tool_call_result_pairing(repo)


def test_invalid_arguments_never_execute_tool():
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('needs', handler=lambda a: 1, input_schema={'required': ['q']})
    kernel, repo, _ = make_kernel(
        scripts=[tool_turn({'name': 'needs', 'arguments': {}}),
                 text_turn('已提示参数缺失')],
        tools=[tool])
    run(kernel.submit('s1', 'main', {'text': '缺参'}))
    assert tool.calls == [], '参数校验失败不得执行工具'
    result = next(e for e in entries(repo) if e.entry_type == 'tool_result')
    assert result.payload['error_code'] == 'tool.invalid_arguments'
    assert_tool_call_result_pairing(repo)


def test_tool_call_argument_deltas_accumulate_before_complete():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('echo', handler=lambda a: a['q'])
    scripts = [[
        ModelEvent('message_start', {}),
        ModelEvent('tool_call_delta', {'id': 'c1', 'name': 'echo',
                                       'arguments_fragment': '{"q": "he'}),
        ModelEvent('tool_call_delta', {'id': 'c1',
                                       'arguments_fragment': 'llo"}'}),
        ModelEvent('tool_call_complete', {'id': 'c1', 'name': 'echo'}),
        ModelEvent('message_complete', {}),
    ], text_turn('回显完成')]
    kernel, _repo, _ = make_kernel(scripts=scripts, tools=[tool])
    run(kernel.submit('s1', 'main', {'text': '增量'}))
    assert tool.calls == [{'q': 'hello'}], '参数增量必须拼成完整 JSON 再执行'


def test_malformed_argument_deltas_become_invalid_arguments():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    tool = FakeTool('echo', handler=lambda a: a)
    scripts = [[
        ModelEvent('message_start', {}),
        ModelEvent('tool_call_delta', {'id': 'c1', 'name': 'echo',
                                       'arguments_fragment': '{broken'}),
        ModelEvent('tool_call_complete', {'id': 'c1', 'name': 'echo'}),
        ModelEvent('message_complete', {}),
    ], text_turn('降级回答')]
    kernel, repo, _ = make_kernel(scripts=scripts, tools=[tool])
    run(kernel.submit('s1', 'main', {'text': '坏参数'}))
    assert tool.calls == []
    result = next(e for e in entries(repo) if e.entry_type == 'tool_result')
    assert result.payload['error_code'] == 'tool.invalid_arguments'
    assert_tool_call_result_pairing(repo)


# ------------------------------------------------------------------ 模型失败/取消

def test_model_failure_commits_error_entry_and_failed_turn():
    from asset_based_agent.technical_platform.agent_core.errors import ModelTimeout
    kernel, repo, _ = make_kernel(scripts=[ModelTimeout('上游超时')])
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    record = repo.get_operation(accepted.operation_id)
    assert record.status == 'failed'
    assert record.error_code == 'model.timeout'
    assert entries(repo)[-1].entry_type == 'error_message'
    turns = repo.turns(accepted.operation_id)
    assert turns[0].status == 'failed'


def test_model_stream_without_terminal_message_is_protocol_failure():
    from asset_based_agent.technical_platform.agent_core.contracts import ModelEvent

    async def factory(request, cancel):
        yield ModelEvent('message_start', {})
        yield ModelEvent('text_delta', {'text': 'partial'})

    kernel, repo, _ = make_kernel(stream_factory=factory)
    accepted = run(kernel.submit('s1', 'main', {'text': 'partial'}))
    assert repo.get_operation(accepted.operation_id).status == 'failed'
    assert repo.get_operation(accepted.operation_id).error_code == 'model.protocol_error'


def test_abort_mid_stream_and_late_deltas_do_not_change_tree():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
    )
    gate = asyncio.Event()

    async def factory(request, cancel):
        yield ModelEvent('message_start', {})
        yield ModelEvent('text_delta', {'text': '前半'})
        await gate.wait()
        yield ModelEvent('text_delta', {'text': '迟到后半'})
        yield ModelEvent('message_complete', {})

    async def scenario():
        kernel, repo, _ = make_kernel(stream_factory=factory)
        accepted = await kernel.submit('s1', 'main', {'text': '问'}, wait=False)
        await asyncio.sleep(0.05)
        await kernel.abort(accepted.operation_id)
        gate.set()
        await asyncio.sleep(0.05)
        return kernel, repo, accepted

    _kernel, repo, accepted = run(scenario())
    record = repo.get_operation(accepted.operation_id)
    assert record.status == 'aborted'
    assert entries(repo)[-1].entry_type == 'error_message'
    texts = [e.payload.get('text', '') for e in entries(repo)]
    assert not any('迟到后半' in t for t in texts), '迟到文本不得进入树'


def test_late_tool_result_after_cancel_blocked():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ModelEvent,
        ToolResult,
    )
    from asset_based_agent.technical_platform.agent_core.fakes import FakeTool
    release = asyncio.Event()

    class HangingTool(FakeTool):
        async def execute(self, context, arguments, cancel):
            await release.wait()
            return ToolResult(status='succeeded', result='迟到结果', content='ok')

    scripts = [[
        ModelEvent('message_start', {}),
        ModelEvent('tool_call_complete', {'id': 'c1', 'name': 'hang',
                                          'arguments': {}}),
        ModelEvent('message_complete', {}),
    ]]

    async def scenario():
        kernel, repo, _ = make_kernel(scripts=scripts, tools=[HangingTool('hang', handler=lambda a: a)])
        accepted = await kernel.submit('s1', 'main', {'text': '问'}, wait=False)
        await asyncio.sleep(0.05)
        await kernel.abort(accepted.operation_id)
        before = len(entries(repo))
        release.set()
        await asyncio.sleep(0.05)
        return repo, accepted, before

    repo, accepted, before = run(scenario())
    assert repo.get_operation(accepted.operation_id).status == 'aborted'
    assert len(entries(repo)) == before, '迟到工具结果不得改变树'
    assert all(e.entry_type != 'tool_result' for e in entries(repo))


# ------------------------------------------------------------------ steer / follow-up

def test_steer_injected_into_next_turn():
    seen_requests = []

    async def factory(request, cancel):
        seen_requests.append(request)
        from asset_based_agent.technical_platform.agent_core.contracts import (
            ModelEvent,
        )
        if len(seen_requests) == 1:
            yield ModelEvent('message_start', {})
            yield ModelEvent('tool_call_complete', {'id': 'c1', 'name': 'noop',
                                                    'arguments': {}})
            yield ModelEvent('message_complete', {})
        else:
            yield ModelEvent('message_start', {})
            yield ModelEvent('text_delta', {'text': '综合回答'})
            yield ModelEvent('message_complete', {})

    async def scenario():
        from asset_based_agent.technical_platform.agent_core.contracts import (
            ToolResult,
        )
        from asset_based_agent.technical_platform.agent_core.fakes import (
            FakeTool,
        )

        class SlowNoop(FakeTool):
            async def execute(self, context, arguments, cancel):
                await asyncio.sleep(0.2)
                return ToolResult(status='succeeded', result=1, content='ok')

        kernel, repo, _ = make_kernel(
            stream_factory=factory, tools=[SlowNoop('noop', handler=lambda a: 1)])
        task = asyncio.ensure_future(kernel.submit('s1', 'main', {'text': '初始'}))
        await asyncio.sleep(0.05)
        receipt = await kernel.steer(repo.open_operations('s1')[0].id,
                                     {'text': '追加约束'})
        assert receipt['queued']
        accepted = await task
        return repo, accepted

    repo, accepted = run(scenario())
    texts = [e.payload.get('text') for e in entries(repo)]
    assert '追加约束' in texts, 'steer 必须成为用户可见 Entry'
    last_request = seen_requests[-1]
    payload_texts = [m['payload'].get('text') for m in last_request.messages]
    assert '追加约束' in payload_texts, 'steer 必须进入下一次模型请求'
    assert repo.get_operation(accepted.operation_id).status == 'completed'


def test_follow_up_runs_after_current_operation():
    async def scenario():
        kernel, repo, _ = make_kernel(
            scripts=[text_turn('答一'), text_turn('答二')])
        accepted1 = await kernel.submit('s1', 'main', {'text': '问一'}, wait=False)
        receipt = await kernel.follow_up('s1', 'main', {'text': '问二'})
        assert receipt['queued']
        await kernel.wait(accepted1.operation_id)
        for _ in range(50):
            if len(repo.open_operations('s1')) == 0 and \
                    len([e for e in entries(repo)
                         if e.entry_type == 'assistant_message']) == 2:
                break
            await asyncio.sleep(0.02)
        return repo

    repo = run(scenario())
    assert [e.payload.get('text') for e in entries(repo)] == [
        '问一', '答一', '问二', '答二']


# ------------------------------------------------------------------ 崩溃恢复

def test_crash_reopen_marks_interrupted_unknown(tmp_path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    repo = SQLiteSessionRepo(store.path, 'alice')
    kernel, repo, _ = make_kernel(
        scripts=[text_turn('不会到达')], repo=repo)
    # 模拟崩溃：operation 停在 running，turn 未闭合
    operation = repo.begin_operation('s1', 'main', user_text='崩', request_id='r9')
    repo.begin_turn(operation.id, 1, input_context_sha256='c' * 64)
    del kernel
    # 重启：新 kernel 对同一库执行恢复
    from asset_based_agent.technical_platform.agent_core.fakes import FakeModelPort
    from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
    recovered = AgentKernel(repo=repo, model=FakeModelPort([text_turn('新回答')]))
    events = []
    recovered.subscribe(events.append)
    report = run(recovered.recover('s1'))
    assert report['interrupted'] == [operation.id]
    record = repo.get_operation(operation.id)
    assert record.status == 'unknown'
    assert entries(repo)[-1].entry_type == 'error_message'
    assert repo.turns(operation.id)[0].status == 'unknown'
    assert any(e.event_type == 'recovery_required' for e in events)
    # lane 立即可用
    accepted = run(recovered.submit('s1', 'main', {'text': '新问'}))
    assert repo.get_operation(accepted.operation_id).status == 'completed'


def test_events_persisted_before_broadcast(tmp_path):
    from asset_based_agent.technical_platform.sessions.sqlite_repository import (
        SQLiteSessionRepo,
    )
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    repo = SQLiteSessionRepo(store.path, 'alice')
    kernel, repo, _ = make_kernel(scripts=[text_turn('你好')], repo=repo)
    run(kernel.submit('s1', 'main', {'text': '问'}))
    persisted = repo.persisted_events('s1')
    kinds = [e['event_type'] for e in persisted]
    assert kinds[0] == 'operation_accepted'
    assert 'turn_started' in kinds and 'message_committed' in kinds
    assert kinds[-1] == 'operation_completed'
    sequences = [e['sequence'] for e in persisted]
    assert sequences == sorted(sequences)


def test_listener_failure_neither_blocks_nor_loses_persistence():
    kernel, repo, _ = make_kernel(scripts=[text_turn('仍在')])

    def bad_listener(event):
        raise RuntimeError('UI 断开')

    kernel.subscribe(bad_listener)
    accepted = run(kernel.submit('s1', 'main', {'text': '问'}))
    assert repo.get_operation(accepted.operation_id).status == 'completed'
    kinds = [e['event_type'] for e in repo.persisted_events('s1')]
    assert 'operation_completed' in kinds, 'UI 断开不影响持久化完成'
