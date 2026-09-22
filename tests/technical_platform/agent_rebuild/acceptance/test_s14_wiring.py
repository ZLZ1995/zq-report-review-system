# S14 灰度接线：feature flags / REVIEW provider / FileScope / 统一工具装配（先红后绿）。
import asyncio

import pytest

from asset_based_agent.technical_platform.agent_core.contracts import (
    ModelEvent,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
from asset_based_agent.technical_platform.business_tools import business_tools
from asset_based_agent.technical_platform.business_tools.service import (
    BusinessRunService,
)
from asset_based_agent.technical_platform.flags import (
    FEATURE_FLAG_ORDER,
    FeatureFlagStore,
)
from asset_based_agent.technical_platform.model_port.provider_factory import (
    production_provider_factory,
    wire_business_service,
)
from asset_based_agent.technical_platform.policies.engine import (
    RuleBasedPolicyEngine,
)
from asset_based_agent.technical_platform.policies.file_scope import (
    build_file_scope,
)
from asset_based_agent.technical_platform.skills import DETAIL, REVIEW
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.tools.assembly import (
    assemble_agent_tools,
)
from asset_based_agent.technical_platform.tools.browser_tools import (
    build_browser_tools,
)


def run(coro):
    return asyncio.run(coro)


def make_store(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    return store, project, session


# ---------------------------------------------------------------- feature flags

def test_ten_flag_categories_in_switch_order():
    assert FEATURE_FLAG_ORDER == (
        'chat', 'platform_query', 'file_readonly_analysis',
        'single_readonly_skill', 'local_generate_skill', 'report_review',
        'review_annotation_copy', 'multi_skill', 'browser_readonly',
        'browser_write_upload')


def test_flags_default_to_old_path_and_switch_independently(tmp_path):
    store = FeatureFlagStore(tmp_path / 'flags.json')
    assert all(not store.enabled(category) for category in FEATURE_FLAG_ORDER)
    store.set_enabled('chat', True)
    store.set_enabled('browser_readonly', True)
    assert store.enabled('chat') is True
    assert store.enabled('multi_skill') is False
    # 可单独退回旧路径
    store.set_enabled('chat', False)
    assert store.enabled('chat') is False
    assert store.enabled('browser_readonly') is True


def test_flags_persist_across_restart(tmp_path):
    path = tmp_path / 'flags.json'
    FeatureFlagStore(path).set_enabled('report_review', True)
    reloaded = FeatureFlagStore(path)
    assert reloaded.enabled('report_review') is True
    assert reloaded.enabled('chat') is False


def test_flags_unknown_category_rejected(tmp_path):
    store = FeatureFlagStore(tmp_path / 'flags.json')
    with pytest.raises(ValueError):
        store.set_enabled('不存在', True)
    with pytest.raises(ValueError):
        store.enabled('不存在')


def test_flags_corrupt_file_fails_closed(tmp_path):
    path = tmp_path / 'flags.json'
    path.write_text('{损坏', encoding='utf-8')
    store = FeatureFlagStore(path)
    assert all(not store.enabled(category) for category in FEATURE_FLAG_ORDER)


# ---------------------------------------------------------------- REVIEW provider 生产接线

def test_production_factory_builds_review_provider():
    factory = production_provider_factory(object(), 'model-x')
    from asset_based_agent.report_review_app.services.remote_review_llm import (
        RemoteReviewLlm,
    )
    provider = factory(REVIEW.id, '审核规则文本')
    assert isinstance(provider, RemoteReviewLlm)
    assert provider.model_id == 'model-x'
    assert provider.skill_instructions == '审核规则文本'


def test_production_factory_builds_detail_provider():
    from asset_based_agent.technical_platform.material_analysis import (
        MaterialAnalysisProvider,
    )
    factory = production_provider_factory(object(), 'model-x')
    provider = factory(DETAIL.id, 'fingerprint-abc')
    assert isinstance(provider, MaterialAnalysisProvider)
    assert provider.model_id == 'model-x'
    assert provider.skill_instructions == 'fingerprint-abc'


def test_production_factory_requires_client_and_model():
    with pytest.raises(ValueError):
        production_provider_factory(None, 'model-x')
    with pytest.raises(ValueError):
        production_provider_factory(object(), '')


def test_wired_business_service_uses_production_factory(tmp_path):
    store, _project, session = make_store(tmp_path)
    service = wire_business_service(store, session, client=object(),
                                    model_id='model-x')
    from asset_based_agent.report_review_app.services.remote_review_llm import (
        RemoteReviewLlm,
    )
    provider = service._provider_factory(REVIEW.id, '规则')
    assert isinstance(provider, RemoteReviewLlm)


# ---------------------------------------------------------------- FileScope 接线

def test_build_file_scope_normalizes_and_dedupes(tmp_path):
    nested = tmp_path / 'a' / '..' / 'b'
    scope = build_file_scope([tmp_path / 'b', nested, str(tmp_path / 'c')])
    assert len(scope.roots) == 2
    assert all('\\' in root or '/' in root for root in scope.roots)


class WriteTool:
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolDescriptor,
        ToolResult,
    )
    descriptor = ToolDescriptor(name='write_out', description='d',
                                input_schema={}, risk='local_create')

    def __init__(self):
        self.executed = []

    async def execute(self, context, arguments, cancel):
        self.executed.append(dict(arguments or {}))
        return WriteTool.ToolResult(status='succeeded', content='写好了')


def _kernel_with_policy(repo, scripts, tools, file_scope, tmp_path):
    return AgentKernel(repo=repo, model=FakeModelPort(scripts), tools=tools,
                       policy=RuleBasedPolicyEngine(), file_scope=file_scope)


def test_directory_outside_file_scope_is_not_executed(tmp_path):
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='u1', title='t',
                        permission_mode='assisted')
    tool = WriteTool()
    inside = tmp_path / 'project'
    inside.mkdir()
    scripts = [
        [ModelEvent('message_start', {}),
         ModelEvent('tool_call_complete',
                    {'id': 'c1', 'name': 'write_out',
                     'arguments': {'directory': str(tmp_path / 'elsewhere')}}),
         ModelEvent('message_complete', {})],
        [ModelEvent('message_start', {}),
         ModelEvent('text_delta', {'text': '未获批准'}),
         ModelEvent('message_complete', {})],
    ]
    kernel = _kernel_with_policy(repo, scripts, [tool],
                                 build_file_scope([inside]), tmp_path)
    run(kernel.submit('s1', 'main', {'text': '写出去'}))
    assert tool.executed == []  # 范围外且无批准人 → 询问未果，不得执行


def test_directory_inside_file_scope_is_allowed(tmp_path):
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='u1', title='t',
                        permission_mode='assisted')
    tool = WriteTool()
    inside = tmp_path / 'project'
    inside.mkdir()
    scripts = [
        [ModelEvent('message_start', {}),
         ModelEvent('tool_call_complete',
                    {'id': 'c1', 'name': 'write_out',
                     'arguments': {'directory': str(inside / 'out')}}),
         ModelEvent('message_complete', {})],
        [ModelEvent('message_start', {}),
         ModelEvent('text_delta', {'text': '已写入'}),
         ModelEvent('message_complete', {})],
    ]
    kernel = _kernel_with_policy(repo, scripts, [tool],
                                 build_file_scope([inside]), tmp_path)
    run(kernel.submit('s1', 'main', {'text': '写进去'}))
    assert tool.executed == [{'directory': str(inside / 'out')}]


# ---------------------------------------------------------------- 统一工具装配

class _StubBrowserBackend:
    def open(self, url):
        return {'url': url}


def test_assembly_merges_business_and_browser_tools(tmp_path):
    store, _project, session = make_store(tmp_path)
    service = BusinessRunService(store, session)
    tools, snapshot = assemble_agent_tools(
        business_service=service,
        browser=build_browser_tools(session, _StubBrowserBackend()))
    names = {tool.descriptor.name for tool in tools}
    assert len(tools) == 8 + 10
    assert 'browser_open' in names
    assert snapshot  # 资源快照覆盖业务工具与浏览器工具来源
    sources = {entry['id'] for entry in snapshot}
    assert 'business.run_harness' in sources
    assert 'browser.tools' in sources


def test_assembly_rejects_name_collision(tmp_path):
    store, _project, session = make_store(tmp_path)
    service = BusinessRunService(store, session)
    clash = business_tools(service)[:1]
    with pytest.raises(ValueError):
        assemble_agent_tools(business_service=service, extra=clash)


def test_assembly_includes_skill_registry_tools(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / 'resources'))
    from skill_fixtures import (
        make_registry,
        make_tool_registry,
        probe_tool,
        write_skill,
    )
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', capabilities=['local_readonly'],
                tools=[probe_tool('echo_tool')])
    registry = make_registry(tmp_path, user=user)
    tools, snapshot = assemble_agent_tools(
        tool_registry=make_tool_registry(registry))
    names = {t.descriptor.name for t in tools}
    assert 'echo_tool' in names
    assert any(entry['id'] == 'alpha' for entry in snapshot)
