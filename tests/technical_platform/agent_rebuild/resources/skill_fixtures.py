"""S07 测试公共辅助：技能目录构造、registry 工厂、echo 执行器。"""
import json
import zipfile


def write_skill(root, skill_id, version, *, name=None, capabilities=(),
                tools=(), executor='echo', config=None, extra_files=None):
    """在 <root>/<id>/<version>/ 下写一个标准技能包，返回版本目录。"""
    version_dir = root / skill_id / version
    version_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        'schema_version': 1,
        'id': skill_id,
        'version': version,
        'name': name or skill_id,
        'description': f'{skill_id} 描述',
        'capabilities': list(capabilities),
        'tools': list(tools),
        'entry': {'executor': executor, 'config': dict(config or {})},
    }
    (version_dir / 'skill.json').write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    for rel, content in (extra_files or {}).items():
        target = version_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
    return version_dir


def probe_tool(name='probe', risk='local_readonly'):
    return {'name': name, 'description': '探针工具',
            'input_schema': {'type': 'object'}, 'risk': risk}


def make_loader(builtin=None, user=None, project=None):
    from asset_based_agent.technical_platform.resources.loader import (
        ResourceLoader,
    )
    return ResourceLoader(builtin_root=builtin, user_root=user,
                          project_root=project)


def make_registry(tmp_path, *, builtin=None, user=None, project=None):
    from asset_based_agent.technical_platform.resources.registry import (
        SkillRegistry,
    )
    if builtin is None:
        # 测试默认与随包内置技能隔离；需要内置种子时请显式构造
        # ResourceLoader()（见 test_builtin_seed_shipped_with_package）
        builtin = tmp_path / '_empty_builtin'
        builtin.mkdir(exist_ok=True)
    return SkillRegistry(
        loader=make_loader(builtin, user, project),
        state_path=tmp_path / 'registry_state.json')


def make_tool_registry(skill_registry, executors=None):
    from asset_based_agent.technical_platform.tools.registry import (
        ToolRegistry,
    )
    return ToolRegistry(skill_registry=skill_registry,
                        executors=executors or {'echo': echo_executor})


async def echo_executor(context, arguments, cancel, config):
    from asset_based_agent.technical_platform.agent_core.contracts import (
        ToolResult,
    )
    return ToolResult(status='succeeded',
                      content=str(config.get('reply', 'ok')),
                      result=dict(arguments))


def make_zip(tmp_path, members, name='skill.zip'):
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w') as archive:
        for member, content in members.items():
            archive.writestr(member, content)
    return path


def zip_manifest(skill_id, version='1.0.0', **overrides):
    manifest = {
        'schema_version': 1,
        'id': skill_id,
        'version': version,
        'name': skill_id,
        'description': 'zip 技能',
        'capabilities': [],
        'tools': [],
        'entry': {'executor': 'echo', 'config': {}},
    }
    manifest.update(overrides)
    return json.dumps(manifest, ensure_ascii=False)
