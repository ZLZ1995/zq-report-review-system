"""S07：SkillRegistry——发现、overlay、enable/disable、zip 安装、
篡改拒绝、版本 pin、reload 与诊断。"""
import shutil

import pytest

from asset_based_agent.technical_platform.agent_core.errors import (
    InvalidRequest,
    ResourceDisabled,
    ResourceManifestInvalid,
    ResourceTampered,
    ResourceVersionChanged,
)
from asset_based_agent.technical_platform.resources.loader import (
    ResourceLoader,
)

from .skill_fixtures import (
    make_registry,
    make_zip,
    probe_tool,
    write_skill,
    zip_manifest,
)


def test_discovers_all_sources_and_lists_for_ui(tmp_path):
    builtin, user, project = (tmp_path / s for s in ('b', 'u', 'p'))
    write_skill(builtin, 'alpha', '1.0.0')
    write_skill(user, 'beta', '1.0.0')
    write_skill(project, 'gamma', '1.0.0')
    registry = make_registry(tmp_path, builtin=builtin, user=user,
                             project=project)
    rows = {row['id']: row for row in registry.list_skills()}
    assert set(rows) == {'alpha', 'beta', 'gamma'}
    assert rows['alpha']['source'] == 'builtin'
    assert rows['beta']['source'] == 'user'
    assert rows['gamma']['source'] == 'project'
    assert all(row['enabled'] for row in rows.values())
    assert all(row['version'] == '1.0.0' for row in rows.values())


def test_project_overlays_user_overlays_builtin(tmp_path):
    builtin, user, project = (tmp_path / s for s in ('b', 'u', 'p'))
    write_skill(builtin, 'alpha', '1.0.0', config={'reply': 'builtin'})
    write_skill(user, 'alpha', '1.1.0', config={'reply': 'user'})
    write_skill(project, 'alpha', '1.0.5', config={'reply': 'project'})
    registry = make_registry(tmp_path, builtin=builtin, user=user,
                             project=project)
    active = registry.resolve('alpha')
    assert active.source == 'project', 'project 优先级高于 user/builtin'
    assert active.manifest.version == '1.0.5'

    registry2 = make_registry(tmp_path / 'x', builtin=builtin, user=user)
    active2 = registry2.resolve('alpha')
    assert active2.source == 'user' and active2.manifest.version == '1.1.0'


def test_highest_version_wins_within_source(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0')
    write_skill(user, 'alpha', '2.0.0')
    registry = make_registry(tmp_path, user=user)
    assert registry.resolve('alpha').manifest.version == '2.0.0'


def test_resolve_unknown_skill_raises_invalid_request(tmp_path):
    registry = make_registry(tmp_path, user=tmp_path / 'u')
    with pytest.raises(InvalidRequest):
        registry.resolve('no-such-skill')


def test_disable_blocks_new_resolution_and_state_persists(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0')
    registry = make_registry(tmp_path, user=user)
    registry.set_enabled('alpha', False)
    with pytest.raises(ResourceDisabled):
        registry.resolve('alpha')
    rows = {row['id']: row for row in registry.list_skills()}
    assert rows['alpha']['enabled'] is False
    # 状态跨实例持久化
    registry2 = make_registry(tmp_path, user=user)
    with pytest.raises(ResourceDisabled):
        registry2.resolve('alpha')
    registry2.set_enabled('alpha', True)
    assert registry2.resolve('alpha').manifest.skill_id == 'alpha'


def test_disabled_skill_still_resolvable_for_pinned_recovery(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0')
    registry = make_registry(tmp_path, user=user)
    sha = registry.resolve('alpha').content_sha256
    registry.set_enabled('alpha', False)
    pinned = registry.resolve_pinned('alpha', '1.0.0', sha)
    assert pinned.manifest.version == '1.0.0', \
        'disable 只影响新任务，不得破坏中断任务的按版本恢复'


# ------------------------------------------------------------------ zip 安装

def test_zip_install_registers_and_resolves(tmp_path):
    archive = make_zip(tmp_path, {
        'zip-skill/skill.json': zip_manifest('zip-skill'),
        'zip-skill/prompts/main.txt': '提示词',
    })
    registry = make_registry(tmp_path, user=tmp_path / 'u')
    installed = registry.install_zip(archive)
    assert installed.manifest.skill_id == 'zip-skill'
    assert installed.manifest.version == '1.0.0'
    assert registry.resolve('zip-skill').content_sha256 == \
        installed.content_sha256
    rows = {row['id']: row for row in registry.list_skills()}
    assert rows['zip-skill']['source'] == 'user'


def test_zip_rejects_traversal_missing_manifest_and_id_mismatch(tmp_path):
    registry = make_registry(tmp_path, user=tmp_path / 'u')
    evil = make_zip(tmp_path, {'../evil.txt': 'x'}, name='evil.zip')
    with pytest.raises(ResourceManifestInvalid):
        registry.install_zip(evil)
    no_manifest = make_zip(tmp_path, {'s/readme.txt': 'x'}, name='bare.zip')
    with pytest.raises(ResourceManifestInvalid):
        registry.install_zip(no_manifest)
    mismatched = make_zip(tmp_path, {
        'dir-a/skill.json': zip_manifest('dir-b')}, name='mismatch.zip')
    with pytest.raises(ResourceManifestInvalid):
        registry.install_zip(mismatched)


def test_zip_reinstall_same_version_rejected(tmp_path):
    archive = make_zip(tmp_path, {'zip-skill/skill.json': zip_manifest('zip-skill')})
    registry = make_registry(tmp_path, user=tmp_path / 'u')
    registry.install_zip(archive)
    with pytest.raises(FileExistsError):
        registry.install_zip(archive)


# ------------------------------------------------------------------ 篡改与 pin

def test_tampered_skill_rejected(tmp_path):
    archive = make_zip(tmp_path, {
        'zip-skill/skill.json': zip_manifest('zip-skill'),
        'zip-skill/prompts/main.txt': '原始提示词',
    })
    registry = make_registry(tmp_path, user=tmp_path / 'u')
    installed = registry.install_zip(archive)
    (installed.root / 'prompts' / 'main.txt').write_text(
        '被篡改的提示词', encoding='utf-8')
    registry.reload()
    with pytest.raises(ResourceTampered):
        registry.resolve('zip-skill')
    rows = {row['id']: row for row in registry.list_skills()}
    assert rows['zip-skill']['tampered'] is True


def test_version_pin_resolution_and_missing_version(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'alpha', '1.0.0', config={'reply': 'v1'})
    write_skill(user, 'alpha', '2.0.0', config={'reply': 'v2'})
    registry = make_registry(tmp_path, user=user)
    sha_v1 = next(d for d in registry.discovered()
                  if d.manifest.skill_id == 'alpha'
                  and d.manifest.version == '1.0.0').content_sha256
    assert registry.resolve('alpha').manifest.version == '2.0.0'
    pinned = registry.resolve_pinned('alpha', '1.0.0', sha_v1)
    assert pinned.manifest.config['reply'] == 'v1'
    with pytest.raises(ResourceTampered):
        registry.resolve_pinned('alpha', '1.0.0', 'f' * 64)
    shutil.rmtree(user / 'alpha' / '1.0.0')
    registry.reload()
    with pytest.raises(ResourceVersionChanged):
        registry.resolve_pinned('alpha', '1.0.0', sha_v1)


def test_reload_picks_up_new_skill_without_code_change(tmp_path):
    user = tmp_path / 'u'
    user.mkdir()
    registry = make_registry(tmp_path, user=user)
    assert registry.list_skills() == []
    write_skill(user, 'hot-skill', '1.0.0',
                capabilities=['local_readonly'], tools=[probe_tool()])
    registry.reload()
    assert registry.resolve('hot-skill').manifest.skill_id == 'hot-skill', \
        '安装新 Skill 只需落盘 + reload，无需改路由代码'


def test_diagnostics_report_invalid_manifest_without_failing(tmp_path):
    user = tmp_path / 'u'
    write_skill(user, 'good', '1.0.0')
    broken = user / 'broken' / '1.0.0'
    broken.mkdir(parents=True)
    (broken / 'skill.json').write_text('{不是JSON', encoding='utf-8')
    registry = make_registry(tmp_path, user=user)
    assert registry.resolve('good').manifest.skill_id == 'good'
    diagnostics = registry.diagnostics()
    assert any(d['status'] == 'invalid_manifest' and 'broken' in d['path']
               for d in diagnostics)


def test_builtin_seed_shipped_with_package(tmp_path):
    """随包内置的 general-assistant 种子技能必须可被默认 Loader 发现。"""
    loader = ResourceLoader()
    discovered, diagnostics = loader.discover()
    ids = {d.manifest.skill_id for d in discovered}
    assert 'general-assistant' in ids
    assert not [d for d in diagnostics if 'general-assistant' in d['path']]
