from asset_based_agent.technical_platform.agent_gateway import AgentGateway
from asset_based_agent.technical_platform.flags import FeatureFlagStore
from asset_based_agent.technical_platform.store import PlatformStore


def _gateway(tmp_path, *, browser_backend=None):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    for category in ('chat', 'local_generate_skill', 'browser_readonly'):
        flags.set_enabled(category, True)
    return store, session, AgentGateway(
        store, session, flags=flags, model_port_factory=lambda: None,
        permission_mode_getter=lambda: 'full',
        browser_backend=browser_backend, force_all_tools=True,
    )


def test_gateway_kernel_uses_composite_resolver_and_scoped_files(tmp_path):
    _store, session, gateway = _gateway(tmp_path)
    kernel = gateway._build_kernel()
    assert kernel._tool_resolver is not None
    assert kernel._file_scope is not None
    assert kernel._file_scope.roots
    tools, snapshot = kernel._tool_resolver.resolve_for_operation()
    assert 'business.run_harness' in {item['id'] for item in snapshot}
    assert 'browser.tools' in {item['id'] for item in snapshot}


class _Browser:
    def open(self, url):
        return {'url': url}


def test_gateway_wires_browser_backend_into_resolved_tools(tmp_path):
    _store, _session, gateway = _gateway(tmp_path, browser_backend=_Browser())
    tools = {tool.descriptor.name: tool for tool in gateway._build_kernel().tools}
    result = __import__('asyncio').run(
        tools['browser_open'].execute(None, {'url': 'https://example.com'}, None))
    assert result.status == 'succeeded'
