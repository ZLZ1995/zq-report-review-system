"""S8-04 故障注入：ZIP 解压中断（ZIP extract interruption）。

注入：合法技能 zip 解压到第 3 个成员时中断 → staging 目录必须清理，
不得出现半成品正式版本目录，重试安装必须成功。
"""
from __future__ import annotations

import zipfile

import pytest

from asset_based_agent.technical_platform.resources.zip_install import (
    install_skill_zip,
)
from tests.technical_platform.agent_rebuild.resources.skill_fixtures import (
    make_zip,
    zip_manifest,
)


def _members():
    return {
        'demo-skill/skill.json': zip_manifest('demo-skill'),
        'demo-skill/a.txt': 'alpha',
        'demo-skill/b.txt': 'beta',
        'demo-skill/c.txt': 'gamma',
    }


def test_zip_extract_interruption_leaves_no_partial_install(
        tmp_path, monkeypatch):
    user_root = tmp_path / 'skills'
    archive = make_zip(tmp_path, _members())
    real_open = zipfile.ZipFile.open
    calls = {'n': 0}

    def flaky_open(self, member, mode='r', pwd=None, **kwargs):
        calls['n'] += 1
        if mode == 'r' and calls['n'] == 3:
            raise OSError('cable pulled mid-extract')
        return real_open(self, member, mode=mode, pwd=pwd, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', flaky_open)
    with pytest.raises(OSError):
        install_skill_zip(archive, user_root)

    leftovers = [p for p in user_root.iterdir()
                 if p.name.startswith('.install-')] if user_root.exists() else []
    assert leftovers == [], f'staging 残留: {leftovers}'
    assert not (user_root / 'demo-skill').exists(), '不得留下半成品版本目录'

    monkeypatch.undo()
    skill_id, version = install_skill_zip(archive, user_root)
    assert (skill_id, version) == ('demo-skill', '1.0.0')
    installed = user_root / 'demo-skill' / '1.0.0'
    assert (installed / 'a.txt').read_text() == 'alpha'
    assert (installed / 'c.txt').read_text() == 'gamma'
