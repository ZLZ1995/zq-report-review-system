"""S01 现状冻结：Skill 选择。

正确行为（必须通过）：执行意图经 stage-1 理解与本地裁决进入业务链。
AGT-04（Skill 硬路由）已在 S07 修复并翻正为正向断言。
"""
from test_consultation_routing import SpyClient, add_file, make_store


def _plan_payload(message_id, file_id):
    return {'schema_version': 1, 'message_intent': 'execute', 'goal': '生成评估明细表',
            'targets': [file_id], 'references': [], 'excluded': [], 'constraints': [],
            'deliverables': ['评估明细表'], 'missing_inputs': [],
            'evidence_message_ids': [message_id],
            'skill_ids': ['valuation-detail-workbook-fill'], 'next_action': 'plan',
            'reply': '好的，开始处理。'}


def test_execute_intent_enters_business_chain_with_selected_skill(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    spy = SpyClient()
    spy.understand_task = lambda payload, *, cancel=None: (
        spy.understand_calls.append(payload) or _plan_payload(payload['message_id'], file_id))
    from asset_based_agent.technical_platform.turn_router import TurnRouter
    outcome = TurnRouter(store, spy).submit(
        session, '生成评估明细表', model_id='m', selected_ids=[file_id])
    assert outcome.kind == 'execution'
    assert outcome.pending is not None and outcome.pending.task_id


def test_skills_are_first_class_tools_in_registry(tmp_path):
    """AGT-04 已在 S07 修复：Skill 经 SkillRegistry/ToolRegistry 注册为
    一等 Tool，落盘 + reload 即可热插拔，无需改路由代码。"""
    import json

    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolResult,
    )
    from asset_based_agent.technical_platform.resources.loader import (
        ResourceLoader,
    )
    from asset_based_agent.technical_platform.resources.registry import (
        SkillRegistry,
    )
    from asset_based_agent.technical_platform.tools import registry
    assert hasattr(registry, 'ToolRegistry')

    async def echo(context, arguments, cancel, config):
        return ToolResult(status='succeeded', content='ok')

    version_dir = tmp_path / 'u' / 'hot-skill' / '1.0.0'
    version_dir.mkdir(parents=True)
    (version_dir / 'skill.json').write_text(json.dumps({
        'schema_version': 1, 'id': 'hot-skill', 'version': '1.0.0',
        'name': '热插拔', 'description': 'd',
        'capabilities': ['local_readonly'],
        'tools': [{'name': 'probe', 'description': 'd',
                   'input_schema': {'type': 'object'},
                   'risk': 'local_readonly'}],
        'entry': {'executor': 'echo', 'config': {}}}), encoding='utf-8')
    skills = SkillRegistry(
        loader=ResourceLoader(builtin_root=tmp_path / 'empty',
                              user_root=tmp_path / 'u'),
        state_path=tmp_path / 'state.json')
    tools, snapshot = registry.ToolRegistry(
        skill_registry=skills, executors={'echo': echo}
    ).resolve_for_operation()
    assert [tool.descriptor.name for tool in tools] == ['probe']
    assert snapshot[0]['id'] == 'hot-skill' and snapshot[0]['sha256']
