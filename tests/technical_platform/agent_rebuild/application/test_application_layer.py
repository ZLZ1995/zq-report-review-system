"""S11：Application Layer——Command/Query/ViewModel/EventProjector 契约。

UI 规则锁定：切换 Session 不停后台 operation；后台完成只更新对应
ViewModel 与未读数；打开 Session 不写 Entry；流式按 operation/turn
定向；最终 Artifact 直接进对话；状态按 Session 隔离；重启后从
Event/Entry 重建；ViewModel 不持有事实状态来源。
"""
import asyncio

import pytest

from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
    ToolResult,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
from asset_based_agent.technical_platform.application import (
    AgentController,
    CommandBus,
    EventProjector,
    SessionController,
    UnknownCommand,
)
from asset_based_agent.technical_platform.application.commands import (
    OpenSession,
    SaveDraft,
    SetPermissionMode,
    SubmitMessage,
    SwitchSession,
)


def run(coro):
    return asyncio.run(coro)


def text_script(text='完成'):
    return [[ModelEvent('message_start', {}),
             ModelEvent('text_delta', {'text': text}),
             ModelEvent('message_complete', {})]]


def make_stack(scripts=(), *, stream_factory=None):
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话一')
    repo.create_session('s2', project_id='p1', owner_id='alice', title='会话二')
    model = (FakeModelPort.from_stream_factory(stream_factory)
             if stream_factory else FakeModelPort(list(scripts)))
    kernel = AgentKernel(repo=repo, model=model)
    projector = EventProjector(repo)
    kernel.subscribe(projector)
    sessions = SessionController(repo, projector)
    agent = AgentController(kernel, projector)
    bus = CommandBus()
    sessions.register(bus)
    agent.register(bus)
    return repo, kernel, projector, sessions, agent, bus


# ------------------------------------------------------------- open/switch

def test_open_session_writes_no_entry():
    repo, _kernel, _projector, _sessions, _agent, bus = make_stack(text_script('一'))
    run(bus.dispatch(SubmitMessage(session_id='s1', text='你好')))
    before = len(repo.entries('s1', 'main'))
    vm = bus.dispatch(OpenSession(session_id='s1'))
    assert len(repo.entries('s1', 'main')) == before  # 打开历史不新增消息
    kinds = [item.kind for item in vm.items]
    assert kinds == ['user', 'assistant']


def test_state_does_not_cross_sessions():
    _repo, _kernel, _projector, _sessions, _agent, bus = make_stack(
        [*text_script('一'), *text_script('二')])
    run(bus.dispatch(SubmitMessage(session_id='s1', text='甲')))
    run(bus.dispatch(SubmitMessage(session_id='s2', text='乙')))
    first = bus.dispatch(OpenSession(session_id='s1'))
    second = bus.dispatch(OpenSession(session_id='s2'))
    assert [i.text for i in first.items if i.kind == 'user'] == ['甲']
    assert [i.text for i in second.items if i.kind == 'user'] == ['乙']


def test_drafts_are_per_session():
    _repo, _kernel, _projector, sessions, _agent, bus = make_stack()
    bus.dispatch(SaveDraft(session_id='s1', text='草稿甲'))
    assert sessions.draft('s1') == '草稿甲'
    assert sessions.draft('s2') == ''


def test_permission_mode_command():
    repo, _kernel, _projector, _sessions, _agent, bus = make_stack()
    bus.dispatch(SetPermissionMode(session_id='s1', mode='request'))
    assert repo.session_permission_mode('s1') == 'request'
    assert repo.session_permission_mode('s2') == 'full'
    with pytest.raises(ValueError):
        bus.dispatch(SetPermissionMode(session_id='s1', mode='root'))


# ------------------------------------------------------------- background

def test_switching_session_does_not_stop_background_operation():
    gate = asyncio.Event()
    calls = []

    def factory(request, cancel):
        calls.append(1)
        if len(calls) == 1:
            async def gated():
                await gate.wait()
                yield ModelEvent('message_start', {})
                yield ModelEvent('text_delta', {'text': '后台完成'})
                yield ModelEvent('message_complete', {})
            return gated()
        return text_script('前台')[0]

    async def scenario():
        repo, kernel, projector, _sessions, _agent, bus = make_stack(
            stream_factory=factory)
        accepted = await kernel.submit('s1', 'main', {'text': '后台任务'},
                                       wait=False)
        await asyncio.sleep(0)  # 让后台 operation 起跑
        bus.dispatch(SwitchSession(session_id='s2'))
        await bus.dispatch(SubmitMessage(session_id='s2', text='前台任务'))
        assert repo.get_operation(accepted.operation_id).status == 'running'
        gate.set()
        await kernel.wait(accepted.operation_id)
        assert repo.get_operation(accepted.operation_id).status == 'completed'
        return projector

    projector = run(scenario())
    assert projector.status_for('s1') == 'idle'


def test_background_completion_updates_only_that_vm_and_unread():
    _repo, _kernel, projector, _sessions, _agent, bus = make_stack(
        [*text_script('后台'), *text_script('前台')])
    bus.dispatch(SwitchSession(session_id='s2'))  # s1 退到后台
    run(bus.dispatch(SubmitMessage(session_id='s1', text='在后台跑')))
    assert projector.status_for('s1') == 'idle'
    assert projector.unread('s1') == 1  # 后台完成只记未读
    assert projector.unread('s2') == 0
    bus.dispatch(SwitchSession(session_id='s1'))  # 打开即清未读
    assert projector.unread('s1') == 0


# ------------------------------------------------------- streaming/artifact

def test_streaming_delta_is_targeted_by_turn_identity():
    _repo, _kernel, projector, _sessions, _agent, _bus = make_stack()
    conversation = projector.conversation('s1', 'main')
    conversation.apply_delta('turn-a', '你')
    conversation.apply_delta('turn-b', '他')
    conversation.apply_delta('turn-a', '好')
    streams = {item.key: item.text for item in conversation.items
               if item.kind == 'streaming'}
    assert streams == {'stream:turn-a': '你好', 'stream:turn-b': '他'}
    conversation.finalize_stream('turn-a')
    remaining = [item.key for item in conversation.items
                 if item.kind == 'streaming']
    assert remaining == ['stream:turn-b']


def test_final_artifacts_appear_in_conversation():
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolDescriptor,
    )

    class ArtifactTool:
        descriptor = ToolDescriptor(name='maker', description='d',
                                    input_schema={}, risk='local_create')

        async def execute(self, context, arguments, cancel):
            return ToolResult(status='succeeded', content='做好',
                              result={'artifacts': [{'name': '评估报告.docx'}]})

    scripts = [
        [ModelEvent('message_start', {}),
         ModelEvent('tool_call_complete',
                    {'id': 'c1', 'name': 'maker', 'arguments': {}}),
         ModelEvent('message_complete', {})],
        *text_script('做完了'),
    ]
    _repo, kernel, _projector, _sessions, _agent, bus = make_stack(scripts)
    kernel.tools = [ArtifactTool()]
    run(bus.dispatch(SubmitMessage(session_id='s1', text='生成')))
    vm = bus.dispatch(OpenSession(session_id='s1'))
    artifacts = [item for item in vm.items if item.kind == 'artifact']
    assert len(artifacts) == 1
    assert artifacts[0].artifacts == ('评估报告.docx',)


# ------------------------------------------------------- status / rebuild

def test_session_scoped_status_replaces_global_banner():
    _repo, _kernel, projector, _sessions, _agent, bus = make_stack(
        text_script('一'))
    assert projector.status_for('s1') == 'idle'
    assert projector.status_for('s2') == 'idle'
    run(bus.dispatch(SubmitMessage(session_id='s1', text='跑')))
    assert projector.status_for('s1') == 'idle'
    assert projector.status_for('s2') == 'idle'  # 互不影响，无全局 banner


def test_projector_rebuilds_from_repo_after_restart():
    repo, kernel, _projector, _sessions, _agent, bus = make_stack(
        text_script('历史回答'))
    run(bus.dispatch(SubmitMessage(session_id='s1', text='历史问题')))
    # 模拟 UI 重启：同一 repo，全新 projector
    fresh = EventProjector(repo)
    kernel.subscribe(fresh)
    fresh.rebuild_all()
    vm = fresh.conversation('s1', 'main')
    assert [i.text for i in vm.items if i.kind == 'user'] == ['历史问题']
    assert [i.text for i in vm.items if i.kind == 'assistant'] == ['历史回答']
    assert fresh.status_for('s1') == 'idle'


# ------------------------------------------------------------- bus / views

def test_command_bus_rejects_unknown_command():
    *_rest, bus = make_stack()
    with pytest.raises(UnknownCommand):
        bus.dispatch(object())


def test_viewmodels_are_pure_data_without_repo_handles():
    _repo, _kernel, projector, _sessions, _agent, bus = make_stack()
    vm = bus.dispatch(OpenSession(session_id='s1'))
    for view_model in (vm, projector.sessions['s1']):
        assert not hasattr(view_model, 'repo')
        assert not hasattr(view_model, 'store')
        assert not hasattr(view_model, 'db')
