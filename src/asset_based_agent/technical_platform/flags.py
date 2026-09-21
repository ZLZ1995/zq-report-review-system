"""S14 灰度 feature flags：10 类任务逐类切换到新 Agent 路径，可单独退回。

- 默认全部 False（旧路径）；损坏的配置文件 fail-closed 回全旧路径；
- 原子写（临时文件 + replace），重启后状态保持；
- 未知类别一律 ValueError（防拼写漂移绕过灰度）。
"""
from __future__ import annotations

import json
import os

FEATURE_FLAG_ORDER = (
    'chat',
    'platform_query',
    'file_readonly_analysis',
    'single_readonly_skill',
    'local_generate_skill',
    'report_review',
    'review_annotation_copy',
    'multi_skill',
    'browser_readonly',
    'browser_write_upload',
)


class FeatureFlagStore:
    def __init__(self, path=None) -> None:
        self._path = str(path) if path is not None else None
        self._flags = {category: False for category in FEATURE_FLAG_ORDER}
        if self._path is not None:
            self._load()

    @property
    def path(self):
        """持久化文件路径；None 表示内存开关（项目未激活期）。"""
        return self._path

    def _load(self) -> None:
        try:
            with open(self._path, encoding='utf-8') as handle:
                data = json.load(handle)
        except FileNotFoundError:
            return
        except (OSError, ValueError):
            return  # 损坏配置 fail-closed：全部保持旧路径
        if not isinstance(data, dict):
            return
        for category in FEATURE_FLAG_ORDER:
            self._flags[category] = data.get(category) is True

    def _save(self) -> None:
        if self._path is None:
            return
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        temporary = self._path + '.tmp'
        with open(temporary, 'w', encoding='utf-8') as handle:
            json.dump(self._flags, handle, ensure_ascii=False, indent=2)
        os.replace(temporary, self._path)

    @staticmethod
    def _check(category: str) -> None:
        if category not in FEATURE_FLAG_ORDER:
            raise ValueError(f'未知灰度类别: {category}')

    def enabled(self, category: str) -> bool:
        self._check(category)
        return self._flags[category]

    def set_enabled(self, category: str, enabled: bool) -> None:
        self._check(category)
        self._flags[category] = bool(enabled)
        self._save()

    def snapshot(self) -> dict:
        return dict(self._flags)
