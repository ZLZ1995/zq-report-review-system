import json

from asset_based_agent.technical_platform.agent_gateway import AgentGateway
from asset_based_agent.technical_platform.flags import FeatureFlagStore
from asset_based_agent.technical_platform.resources.loader import ResourceLoader
from asset_based_agent.technical_platform.resources.registry import SkillRegistry
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.tools.registry import ToolRegistry


def test_gateway_exposes_registered_skill_tools(tmp_path):
    skill_root = tmp_path / 'skills' / 'demo-skill' / '1.0.0'
    skill_root.mkdir(parents=True)
    (skill_root / 'skill.json').write_text(json.dumps({
        'schema_version': 1,
        'id': 'demo-skill',
        'version': '1.0.0',
        'name': 'Demo',
        'description': 'test skill',
        'capabilities': ['local_readonly'],
        'tools': [{
            'name': 'demo_lookup',
            'description': 'lookup',
            'input_schema': {'type': 'object'},
            'risk': 'local_readonly',
        }],
        'entry': {'executor': 'demo', 'config': {}},
    }, ensure_ascii=False), encoding='utf-8')
    registry = SkillRegistry(
        loader=ResourceLoader(user_root=tmp_path / 'skills'),
        state_path=tmp_path / 'skill-state.json',
    )
    tools = ToolRegistry(skill_registry=registry, executors={
        'demo': lambda _context, _args, _cancel, _config: None,
    })
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    flags = FeatureFlagStore(tmp_path / 'flags.json')
    flags.set_enabled('chat', True)
    flags.set_enabled('local_generate_skill', True)
    gateway = AgentGateway(
        store, session, flags=flags, model_port_factory=lambda: None,
        permission_mode_getter=lambda: 'risk', tool_registry=tools,
    )

    assert 'demo_lookup' in {tool.descriptor.name
                             for tool in gateway.active_tools()}
