import hashlib
import json
import zipfile

import pytest

from asset_based_agent.technical_platform.skill_installation import SkillInstallation
from asset_based_agent.technical_platform.store import PlatformStore


def make_package(tmp_path, version="1.0.0", rules="rules", dependencies=None):
    path = tmp_path / "package.zip"
    manifest = {"schema_version": 1, "id": "test.review", "name": "Test", "version": version,
                "adapter": "report.review", "capabilities": ["read_selected_files"],
                "dependencies": dependencies or {},
                "files": {"SKILL.md": hashlib.sha256(rules.encode()).hexdigest()}}
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("SKILL.md", rules)
    return path


def test_install_requires_confirmation_persists_and_is_owner_scoped(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    manager = SkillInstallation(store)
    path = make_package(tmp_path)
    with pytest.raises(ValueError):
        manager.install(path, confirmed=False)
    assert manager.list_versions() == []
    manager.install(path, confirmed=True)
    path.unlink()
    reopened = SkillInstallation(PlatformStore(store.path, "alice"))
    assert reopened.load("test.review", "1.0.0").instructions == "rules"
    assert reopened.list_versions()[0]["enabled"] == 0
    other = SkillInstallation(PlatformStore(store.path, "bob"))
    assert other.list_versions() == []
    with pytest.raises(PermissionError):
        other.load("test.review", "1.0.0")


def test_same_version_cannot_be_overwritten_and_switch_can_rollback(tmp_path):
    manager = SkillInstallation(PlatformStore(tmp_path / "db.sqlite", "alice"))
    manager.install(make_package(tmp_path), confirmed=True)
    with pytest.raises(ValueError):
        manager.install(make_package(tmp_path, rules="changed"), confirmed=True)
    manager.install(make_package(tmp_path, version="2.0.0"), confirmed=True)
    for version in ("1.0.0", "2.0.0", "1.0.0"):
        manager.activate("test.review", version, confirmed=True)
        assert [r["version"] for r in manager.list_versions() if r["enabled"]] == [version]
    manager.disable("test.review", confirmed=True)
    assert not any(r["enabled"] for r in manager.list_versions())


def test_missing_dependencies_and_active_tasks_block_activation(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    manager = SkillInstallation(store)
    manager.install(make_package(tmp_path, dependencies={"zq-nonexistent-test-dep": ">=1"}), confirmed=True)
    with pytest.raises(ValueError, match="依赖"):
        manager.activate("test.review", "1.0.0", confirmed=True)
    manager.install(make_package(tmp_path, version="2.0.0"), confirmed=True)
    session = store.create_session(store.create_project("one"))
    run = store.start_run(session, {"skill_id": "test.review"})
    with pytest.raises(ValueError, match="未结束"):
        manager.activate("test.review", "2.0.0", confirmed=True)
    with pytest.raises(ValueError, match="未结束"):
        manager.disable("test.review", confirmed=True)
    store.transition(run, "cancelled", "test")
    manager.activate("test.review", "2.0.0", confirmed=True)


def test_failed_switch_preserves_active_version_and_tampering_is_rejected(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    manager = SkillInstallation(store)
    manager.install(make_package(tmp_path), confirmed=True)
    manager.activate("test.review", "1.0.0", confirmed=True)
    manager.install(make_package(tmp_path, version="2.0.0", dependencies={"zq-missing-dep": ">=1"}), confirmed=True)
    with pytest.raises(ValueError):
        manager.activate("test.review", "2.0.0", confirmed=True)
    assert [r["version"] for r in manager.list_versions() if r["enabled"]] == ["1.0.0"]
    with pytest.raises(ValueError):
        manager.disable("test.review", confirmed=False)
    with pytest.raises(ValueError):
        manager.activate("test.review", "1.0.0", confirmed=False)
    with store.connect() as db:
        db.execute("UPDATE installed_skills SET sha256=? WHERE version='1.0.0'", ("0" * 64,))
    with pytest.raises(ValueError, match="完整性"):
        manager.load("test.review", "1.0.0")


def test_identical_install_is_idempotent_with_single_audit_event(tmp_path):
    store = PlatformStore(tmp_path / "db.sqlite", "alice")
    manager = SkillInstallation(store)
    path = make_package(tmp_path)
    manager.install(path, confirmed=True)
    manager.install(path, confirmed=True)
    assert len(manager.list_versions()) == 1
    with store.connect() as db:
        assert db.execute("SELECT count(*) FROM skill_install_events").fetchone()[0] == 1


def test_package_replaced_after_confirmation_is_not_installed(tmp_path):
    from asset_based_agent.technical_platform.skill_package import inspect_package

    manager = SkillInstallation(PlatformStore(tmp_path / "db.sqlite", "alice"))
    path = make_package(tmp_path)
    expected = inspect_package(path).sha256
    make_package(tmp_path, rules="changed after preview")
    with pytest.raises(ValueError, match="已变化"):
        manager.install(path, confirmed=True, expected_sha256=expected)
    assert manager.list_versions() == []
