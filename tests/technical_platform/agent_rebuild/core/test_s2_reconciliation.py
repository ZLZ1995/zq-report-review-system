"""S2-03 客户端对账：stale turn 按服务端真实状态收束（先红后绿）。

映射规则（总任务书 S2-03）：
- succeeded → replay
- failed → 本地 fail
- streaming + live lease → 保持 busy
- uncertain/disconnected → reconciliation_required（绝不自动重放）
- 不存在 → 本地 fail / manual
"""


def make_repo():
    from asset_based_agent.technical_platform.agent_core.fakes import (
        InMemorySessionRepo,
    )
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    return repo


def unknown_op_with_stale_turn(repo, request_id='req-1'):
    operation = repo.begin_operation('s1', 'main', user_text='问',
                                     request_id='r1')
    repo.begin_turn(operation.id, 1, input_context_sha256='x',
                    model_request_id=request_id)
    repo.interrupt_operation(operation.id, code='agent.interrupted',
                             summary='进程中断')
    return operation


def test_stale_local_turn_reconciles_succeeded_server_request():
    from asset_based_agent.technical_platform.agent_core.reconciliation import (
        reconcile_unknown_operation,
    )
    repo = make_repo()
    operation = unknown_op_with_stale_turn(repo)
    calls = []

    def query(request_id):
        calls.append(('query', request_id))
        return {'status': 'succeeded', 'billing_request_id': 'b1',
                'replay_available': True, 'error_code': ''}

    def replay(request_id):
        calls.append(('replay', request_id))
        return [{'kind': 'text_delta', 'data': {'text': '对账恢复文本'}},
                {'kind': 'message_complete', 'data': {}}]

    result = reconcile_unknown_operation(repo, operation.id, query=query,
                                         replay=replay)
    assert result == 'completed'
    assert calls == [('query', 'req-1'), ('replay', 'req-1')]
    assert repo.get_operation(operation.id).status == 'completed'
    texts = [e.payload.get('text', '') for e in repo.entries('s1', 'main')
             if e.entry_type == 'assistant_message']
    assert any('对账恢复文本' in t for t in texts), '回放文本必须落入本地树'


def test_stale_local_turn_reconciles_failed_server_request():
    from asset_based_agent.technical_platform.agent_core.reconciliation import (
        reconcile_unknown_operation,
    )
    repo = make_repo()
    operation = unknown_op_with_stale_turn(repo)

    def query(_request_id):
        return {'status': 'failed', 'billing_request_id': 'b1',
                'replay_available': False, 'error_code': 'model.timeout'}

    def replay(_request_id):
        raise AssertionError('failed 请求绝不回放')

    result = reconcile_unknown_operation(repo, operation.id, query=query,
                                         replay=replay)
    assert result == 'failed'
    record = repo.get_operation(operation.id)
    assert record.status == 'failed'
    assert record.error_code == 'model.timeout'


def test_uncertain_server_request_never_replayed_automatically():
    from asset_based_agent.technical_platform.agent_core.reconciliation import (
        reconcile_unknown_operation,
    )
    repo = make_repo()
    operation = unknown_op_with_stale_turn(repo)

    def query(_request_id):
        return {'status': 'uncertain', 'billing_request_id': 'b1',
                'replay_available': False,
                'error_code': 'provider_usage_missing'}

    def replay(_request_id):
        raise AssertionError('uncertain 请求绝不自动回放')

    result = reconcile_unknown_operation(repo, operation.id, query=query,
                                         replay=replay)
    assert result == 'reconciliation_required'
    record = repo.get_operation(operation.id)
    assert record.status == 'unknown', 'uncertain 不得直接改写为 failed'
    texts = [e.payload.get('text', '') for e in repo.entries('s1', 'main')
             if e.entry_type == 'error_message']
    assert any('对账' in t for t in texts), '必须给用户可见的对账提示'


def test_streaming_server_request_keeps_busy_without_touch():
    from asset_based_agent.technical_platform.agent_core.reconciliation import (
        reconcile_unknown_operation,
    )
    repo = make_repo()
    operation = unknown_op_with_stale_turn(repo)

    def query(_request_id):
        return {'status': 'streaming', 'billing_request_id': 'b1',
                'replay_available': False, 'error_code': ''}

    result = reconcile_unknown_operation(repo, operation.id, query=query,
                                         replay=None)
    assert result == 'busy'
    assert repo.get_operation(operation.id).status == 'unknown'


def test_unknown_server_request_fails_locally():
    from asset_based_agent.technical_platform.agent_core.reconciliation import (
        reconcile_unknown_operation,
    )
    repo = make_repo()
    operation = unknown_op_with_stale_turn(repo)
    result = reconcile_unknown_operation(repo, operation.id,
                                         query=lambda _rid: None, replay=None)
    assert result == 'failed'
    assert repo.get_operation(operation.id).status == 'failed'
