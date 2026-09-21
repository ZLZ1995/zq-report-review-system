"""S07：Skill manifest 校验——结构、能力目录、越权声明防护。"""
import pytest

from asset_based_agent.technical_platform.agent_core.errors import (
    ResourceManifestInvalid,
)
from asset_based_agent.technical_platform.resources.manifest import (
    parse_manifest,
)


def base_manifest(**overrides):
    manifest = {
        'schema_version': 1,
        'id': 'demo-skill',
        'version': '1.0.0',
        'name': '演示技能',
        'description': '描述',
        'capabilities': [],
        'tools': [],
        'entry': {'executor': 'echo', 'config': {}},
    }
    manifest.update(overrides)
    return manifest


def test_valid_manifest_round_trip():
    manifest = parse_manifest(base_manifest(
        capabilities=['local_readonly'],
        tools=[{'name': 'probe', 'description': 'd',
                'input_schema': {'type': 'object'}, 'risk': 'local_readonly'}],
        entry={'executor': 'echo', 'config': {'reply': 'ok'}}))
    assert manifest.skill_id == 'demo-skill'
    assert manifest.version == '1.0.0'
    assert manifest.capabilities == ('local_readonly',)
    assert manifest.executor == 'echo'
    assert manifest.config == {'reply': 'ok'}
    assert manifest.tools[0].name == 'probe'
    assert manifest.tools[0].risk == 'local_readonly'


def test_missing_id_rejected():
    manifest = base_manifest()
    del manifest['id']
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(manifest)


def test_bad_id_format_rejected():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(id='Bad ID!'))


def test_bad_version_format_rejected():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(version='1.0'))


def test_unknown_schema_version_rejected():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(schema_version=2))


def test_unknown_capability_rejected():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(capabilities=['fly_to_moon']))


def test_tool_risk_outside_catalog_rejected():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(tools=[{
            'name': 't', 'description': 'd', 'input_schema': {},
            'risk': 'teleport'}]))


def test_tool_risk_must_be_covered_by_declared_capabilities():
    """Skill 不能隐式获得未声明的能力（PolicyEngine 绕过防护）。"""
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(
            capabilities=[],
            tools=[{'name': 't', 'description': 'd', 'input_schema': {},
                    'risk': 'browser_action'}]))


def test_tool_required_must_be_string_list():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(
            capabilities=['local_readonly'],
            tools=[{'name': 't', 'description': 'd',
                    'input_schema': {'required': 'oops'},
                    'risk': 'local_readonly'}]))


def test_entry_executor_required():
    with pytest.raises(ResourceManifestInvalid):
        parse_manifest(base_manifest(entry={'config': {}}))
