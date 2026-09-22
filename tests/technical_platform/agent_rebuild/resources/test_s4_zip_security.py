"""S4-01 Skill ZIP 安全重写：恶意 ZIP 不得越界写入、不得留半成品（先红后绿）。

验收矩阵（任务书 S4-01）：`../evil`、`..\\evil`、`a/../../evil`、`C:\\evil`、
`/evil`、大小写重复、symlink 条目、超大成员数、zip bomb、解压中途异常。
最终断言：user_root 外无任何新文件；target version 目录不存在或完整安装。
"""
from __future__ import annotations

import stat
import zipfile

import pytest

from asset_based_agent.technical_platform.agent_core.errors import (
    ResourceManifestInvalid,
)
from asset_based_agent.technical_platform.resources.zip_install import (
    MAX_MEMBERS,
    install_skill_zip,
)

from .skill_fixtures import make_zip, zip_manifest


def _raw_zip(tmp_path, entries, name='evil.zip', compression=zipfile.ZIP_STORED):
    """entries: [(member, data)] 或 [(member, (data, external_attr))]"""
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w', compression=compression) as archive:
        for member, payload in entries:
            if isinstance(payload, tuple):
                info = zipfile.ZipInfo(member)
                info.external_attr = payload[1]
                archive.writestr(info, payload[0])
            else:
                archive.writestr(member, payload)
    return path


def _assert_no_leak(tmp_path, user_root):
    """user_root 外无任何新文件；user_root 内无半成品/ staging 残留。"""
    outside = [p for p in tmp_path.rglob('*')
               if p.is_file() and user_root not in p.parents
               and p.suffix != '.zip']
    assert outside == [], f'user_root 外出现新文件: {outside}'
    if user_root.exists():
        leftovers = [p for p in user_root.iterdir()
                     if p.name.startswith('.install-')]
        assert leftovers == [], f'staging 残留: {leftovers}'


def test_backslash_traversal_rejected(tmp_path):
    user_root = tmp_path / 'skills'
    evil = _raw_zip(tmp_path, [('..\\evil.txt', 'x')])
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(evil, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_nested_traversal_rejected(tmp_path):
    user_root = tmp_path / 'skills'
    evil = _raw_zip(tmp_path, [('a/../../evil.txt', 'x')])
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(evil, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_drive_prefix_rejected(tmp_path):
    user_root = tmp_path / 'skills'
    evil = _raw_zip(tmp_path, [('C:\\evil.txt', 'x')])
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(evil, user_root)
    evil2 = _raw_zip(tmp_path, [('C:/evil.txt', 'x')], name='evil2.zip')
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(evil2, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_absolute_path_rejected(tmp_path):
    user_root = tmp_path / 'skills'
    evil = _raw_zip(tmp_path, [('/evil.txt', 'x')])
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(evil, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_case_insensitive_duplicate_rejected(tmp_path):
    user_root = tmp_path / 'skills'
    evil = _raw_zip(tmp_path, [
        ('dup/skill.json', zip_manifest('dup')),
        ('dup/A.txt', '1'),
        ('dup/a.txt', '2'),
    ])
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(evil, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_symlink_and_special_entries_rejected(tmp_path):
    user_root = tmp_path / 'skills'
    link = _raw_zip(tmp_path, [
        ('ln/skill.json', zip_manifest('ln')),
        ('ln/evil', ('x', (stat.S_IFLNK | 0o777) << 16)),
    ], name='link.zip')
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(link, user_root)
    fifo = _raw_zip(tmp_path, [
        ('ff/skill.json', zip_manifest('ff')),
        ('ff/pipe', ('x', (stat.S_IFIFO | 0o644) << 16)),
    ], name='fifo.zip')
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(fifo, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_member_count_limit_enforced(tmp_path):
    assert MAX_MEMBERS < 200_000, '任务书要求 20 万成员必须被拒'
    user_root = tmp_path / 'skills'
    entries = [('many/skill.json', zip_manifest('many'))]
    entries += [(f'many/f{i:06d}.txt', 'x') for i in range(MAX_MEMBERS)]
    bomb = _raw_zip(tmp_path, entries, name='many.zip')
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(bomb, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_zip_bomb_rejected(tmp_path):
    """1KB 级压缩体展开成数十 MB：展开总量/压缩比双重上限拒绝。"""
    user_root = tmp_path / 'skills'
    payload = b'0' * (40 * 1024 * 1024)  # 40MB 零字节，deflate 后 ~40KB
    bomb = _raw_zip(tmp_path, [
        ('bomb/skill.json', zip_manifest('bomb')),
        ('bomb/data.bin', payload),
    ], name='bomb.zip', compression=zipfile.ZIP_DEFLATED)
    with pytest.raises(ResourceManifestInvalid):
        install_skill_zip(bomb, user_root)
    _assert_no_leak(tmp_path, user_root)


def test_mid_extraction_failure_leaves_no_partial_install(
        tmp_path, monkeypatch):
    """解压中途抛异常：target version 目录不存在，staging 无残留。"""
    user_root = tmp_path / 'skills'
    archive = make_zip(tmp_path, {
        'fragile/skill.json': zip_manifest('fragile'),
        'fragile/a.txt': '甲',
        'fragile/b.txt': '乙',
    })
    original_open = zipfile.ZipFile.open

    def flaky_open(self, name, *args, **kwargs):
        member = getattr(name, 'filename', None) or str(name)
        if member.endswith('b.txt'):
            raise RuntimeError('disk error mid-extraction')
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, 'open', flaky_open)
    with pytest.raises(RuntimeError):
        install_skill_zip(archive, user_root)
    monkeypatch.undo()
    assert not (user_root / 'fragile').exists(), '不允许半成品版本目录'
    _assert_no_leak(tmp_path, user_root)


def test_successful_install_has_no_staging_leftover(tmp_path):
    user_root = tmp_path / 'skills'
    archive = make_zip(tmp_path, {
        'clean/skill.json': zip_manifest('clean'),
        'clean/prompts/main.txt': '提示词',
    })
    skill_id, version = install_skill_zip(archive, user_root)
    assert (skill_id, version) == ('clean', '1.0.0')
    assert (user_root / 'clean' / '1.0.0' / 'prompts' / 'main.txt').read_text(
        encoding='utf-8') == '提示词'
    _assert_no_leak(tmp_path, user_root)
