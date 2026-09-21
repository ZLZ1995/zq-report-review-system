# S14 完整验收矩阵：40 项定义完整性 + 验收项 1/2 的端到端探针。
import asyncio
from pathlib import Path

from asset_based_agent.technical_platform.acceptance import MATRIX, STATUSES
from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel

TESTS_ROOT = Path(__file__).resolve().parents[3]


def run(coro):
    return asyncio.run(coro)


def test_matrix_covers_exactly_forty_items():
    assert len(MATRIX) == 40
    assert [item.number for item in MATRIX] == list(range(1, 41))
    for item in MATRIX:
        assert item.status in STATUSES, item.number
        assert item.requirement.strip()


def test_every_automated_item_has_existing_evidence():
    missing = []
    for item in MATRIX:
        if item.status == 'manual_environment':
            assert item.note, f'#{item.number} 需说明环境依赖'
            continue
        assert item.evidence, f'#{item.number} 缺少证据测试'
        for relative in item.evidence:
            if not (TESTS_ROOT / relative).exists():
                missing.append((item.number, relative))
    assert not missing, missing


def _chat_kernel(repo, scripts, tools=()):
    repo.create_session('s1', project_id='p1', owner_id='u1', title='t')
    return AgentKernel(repo=repo, model=FakeModelPort(scripts), tools=tools)


def test_item1_plain_greeting_answers_without_skill():
    repo = InMemorySessionRepo()
    kernel = _chat_kernel(repo, [[
        ModelEvent('message_start', {}),
        ModelEvent('text_delta', {'text': '你好！请问有什么可以帮你？'}),
        ModelEvent('message_complete', {})]])
    run(kernel.submit('s1', 'main', {'text': '你好'}))
    entries = repo.entries('s1', 'main')
    assert not [e for e in entries if e.entry_type == 'tool_call']
    assistant = [e for e in entries if e.entry_type == 'assistant_message']
    assert assistant and '你好' in assistant[-1].payload['text']


def test_item2_capability_answer_grounded_in_registry():
    from asset_based_agent.technical_platform.agent_core.context_builder import (
        ContextBuilder,
    )
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolDescriptor,
    )

    class _Tool:
        descriptor = ToolDescriptor(name='generate_report', description='生成报告',
                                    input_schema={}, risk='local_create')
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='u1', title='t')
    operation = repo.begin_operation('s1', 'main', user_text='你能帮我做什么',
                                     request_id='r1')
    built = ContextBuilder().build(repo=repo, operation=operation,
                                   tools=[_Tool()])
    listing = next(m['payload']['text'] for m in built.messages
                   if '【当前 Tool 描述】' in m['payload'].get('text', ''))
    # 能力回答的候选来源只能是当前 Resource/Tool Registry
    assert 'generate_report' in listing
