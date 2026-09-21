import json

import pytest

from asset_based_agent.technical_platform import generation
from asset_based_agent.technical_platform.skills import DETAIL, HISTORY, digest


def test_template_is_not_a_runtime_input():
    files = [{'id': 'source', 'name': 'source.xlsx'}]
    generation.validate_roles(HISTORY.id, files, {'source_excel': 'source'})
    with pytest.raises(ValueError):
        generation.validate_roles(HISTORY.id, files, {'source_excel': 'source', 'template': 'source'})
    assert all(role[0] != 'template' for role in generation.INPUT_ROLES[DETAIL.id])


def test_missing_lock_prevents_generation(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, 'bundle_directory', lambda _: tmp_path)
    with pytest.raises(ValueError, match='锁定模板'):
        generation.bundle_fingerprint(HISTORY.id)


def test_locked_template_checks_hash_and_containment(tmp_path, monkeypatch):
    monkeypatch.setattr(generation, 'bundle_directory', lambda _: tmp_path)
    assets = tmp_path / 'assets'
    assets.mkdir()
    template = assets / 'template.docx'
    template.write_bytes(b'fixture')
    data = {'schema_version': 1, 'skill_id': HISTORY.id,
            'path': 'assets/template.docx', 'sha256': digest(template)}
    lock = tmp_path / 'template.lock.json'
    lock.write_text(json.dumps(data))
    assert generation.locked_template(HISTORY.id) == template
    template.write_bytes(b'changed')
    with pytest.raises(ValueError, match='修改'):
        generation.locked_template(HISTORY.id)
    data['path'] = '../other.docx'
    lock.write_text(json.dumps(data))
    with pytest.raises(PermissionError):
        generation.locked_template(HISTORY.id)
