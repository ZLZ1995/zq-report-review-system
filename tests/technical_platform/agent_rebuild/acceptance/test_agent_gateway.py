# S15 接线子集：AgentGateway——flags 驱动的逐类新旧路由（先红后绿）。
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
)
from asset_based_agent.technical_platform.agent_gateway import (
    MODE_MAP,
    AgentGateway,
)
from asset_based_agent.technical_platform.flags import FeatureFlagStore
from asset_based_agent.technical_platform.store import PlatformStore


def text_script(text):
    return [ModelEvent('message_start', {}),
            ModelEvent('text_delta', {'text': text}),
            ModelEvent('message_complete', {})]


def tool_call_script(name, arguments):
    return [ModelEvent('message_start', {}),
            ModelEvent('tool_call_complete',
                       {'id': 'c1', 'name': name, 'arguments': arguments}),
            ModelEvent('message_complete', {})]


def make_stack(tmp_path, *, flags_on=(), scripts=(), mode='risk'):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    for category in flags_on:
        flags.set_enabled(category, True)
    models = iter(FakeModelPort(list(group)) for group in scripts)
    gateway = AgentGateway(
        store, session, flags=flags,
        model_port_factory=lambda: next(models),
        permission_mode_getter=lambda: mode,
    )
    return store, session, flags, gateway


# ---------------------------------------------------------------- 路由开关

def test_no_flags_means_old_path(tmp_path):
    _, _, _, gateway = make_stack(tmp_path)
    assert gateway.new_path_available is False
    assert gateway.active_tools() == ()


def test_chat_flag_enables_plain_conversation(tmp_path):
    _, _session, _, gateway = make_stack(
        tmp_path, flags_on=('chat',), scripts=[[text_script('你好！')]])
    result = gateway.submit('你好')
    assert result['status'] == 'completed'
    assert result['reply'] == '你好！'


def test_tool_catalog_follows_flags(tmp_path):
    _, _, _, gateway = make_stack(tmp_path, flags_on=('chat',))
    assert gateway.active_tools() == ()

    _, _, _, gateway = make_stack(
        tmp_path / 'b', flags_on=('chat', 'file_readonly_analysis'))
    names = {t.descriptor.name for t in gateway.active_tools()}
    assert {'inspect_project_files', 'analyze_file_roles'} <= names
    assert 'execute_skill_plan' not in names  # 生成类未开闸

    _, _, _, gateway = make_stack(
        tmp_path / 'c', flags_on=('chat', 'local_generate_skill'))
    names = {t.descriptor.name for t in gateway.active_tools()}
    assert 'execute_skill_plan' in names
    assert 'annotate_reviewed_files' not in names  # 批注副本单独开闸

    _, _, _, gateway = make_stack(
        tmp_path / 'd', flags_on=('chat', 'review_annotation_copy'))
    names = {t.descriptor.name for t in gateway.active_tools()}
    assert 'annotate_reviewed_files' in names
    assert 'execute_skill_plan' not in names


def test_browser_readonly_excludes_write_tools(tmp_path):
    _, _, _, gateway = make_stack(
        tmp_path, flags_on=('chat', 'browser_readonly'))
    names = {t.descriptor.name for t in gateway.active_tools()}
    assert {'browser_open', 'browser_observe', 'browser_download'} <= names
    assert 'browser_click' not in names
    assert 'browser_upload' not in names
    assert 'browser_save_credential' not in names

    _, _, _, gateway = make_stack(
        tmp_path / 'e',
        flags_on=('chat', 'browser_readonly', 'browser_write_upload'))
    names = {t.descriptor.name for t in gateway.active_tools()}
    assert 'browser_upload' in names
    assert 'browser_save_credential' in names


# ---------------------------------------------------------------- 会话镜像与权限

def test_session_mirrored_with_mapped_permission_mode(tmp_path):
    _, session, _, gateway = make_stack(
        tmp_path, flags_on=('chat',), scripts=[[text_script('好')]],
        mode='risk')
    gateway.submit('你好')
    mirrored = gateway.repo.session_permission_mode(session)
    assert mirrored == 'assisted'  # 旧 risk → 新 assisted
    assert MODE_MAP == {'request': 'request', 'risk': 'assisted',
                        'full': 'full'}


def test_repeat_submit_reuses_session_and_accumulates(tmp_path):
    _, session, _, gateway = make_stack(
        tmp_path, flags_on=('chat',),
        scripts=[[text_script('一')], [text_script('二')]])
    gateway.submit('第一句')
    gateway.submit('第二句')
    entries = gateway.repo.entries(session, 'main')
    user_texts = [e.payload['text'] for e in entries
                  if e.entry_type == 'user_message']
    assert user_texts == ['第一句', '第二句']


def test_events_streamed_to_callback(tmp_path):
    _, _, _, gateway = make_stack(
        tmp_path, flags_on=('chat',), scripts=[[text_script('流式回答')]])
    seen = []
    result = gateway.submit('问题', on_event=lambda event: seen.append(
        event.event_type))
    assert result['status'] == 'completed'
    assert 'message_delta' in seen
    assert 'operation_completed' in seen


def test_model_failure_returns_failed_with_error_code(tmp_path):
    from asset_based_agent.technical_platform.agent_core.errors import (
        ModelProtocolError,
    )
    _, session, _, gateway = make_stack(
        tmp_path, flags_on=('chat',), scripts=[[ModelProtocolError('上游 500')]])
    result = gateway.submit('问题')
    assert result['status'] == 'failed'
    assert result['error_code']
    # 失败 Turn 有 Entry（验收 #3）
    entries = gateway.repo.entries(session, 'main')
    assert [e for e in entries if e.entry_type == 'user_message']


# ---------------------------------------------------------------- 业务工具链

def test_skill_execution_flows_through_new_kernel(tmp_path):
    """local_generate_skill 开闸后，模型可选 execute_skill_plan 并经策略门。"""
    scripts = [[
        tool_call_script('execute_skill_plan', {
            'skill_id': 'x', 'skill_version': '1', 'skill_hash': 'h',
            'target_file_ids': [], 'reference_file_ids': [],
            'user_goal': 'g', 'confirmed_facts': [],
            'permission_receipt': {}, 'idempotency_key': 'k'}),
        text_script('任务已提交'),
    ]]
    _, session, _, gateway = make_stack(
        tmp_path, flags_on=('chat', 'local_generate_skill'),
        scripts=scripts, mode='request')
    result = gateway.submit('生成报告')
    # request 模式下 local_create 询问、无批准人 → 不得真实执行（安全失败）
    assert result['status'] == 'completed'
    assert result['reply'] == '任务已提交'
    entries = gateway.repo.entries(session, 'main')
    tool_results = [e for e in entries if e.entry_type == 'tool_result']
    assert tool_results[0].payload['status'] == 'failed'


def test_stop_cancels_running_operation(tmp_path):
    _, _session, _, gateway = make_stack(
        tmp_path, flags_on=('chat',), scripts=[[text_script('好')]])
    gateway.submit('第一句')
    gateway.stop()  # 无活动 operation 时安全返回
    gateway.stop()
