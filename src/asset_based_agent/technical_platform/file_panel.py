"""S11 文件面板：角色识别、期间识别、行标签、过滤与详情（纯逻辑层）。

铁律：
- 派生信息全部来自真实文件记录与任务快照，绝不臆造；
- 列表行默认不显示 hash（hash 仅在文件详情中展示）；
- 期间识别只做保守匹配，识别不出就返回 None，界面显示“期间未识别”。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# ------------------------------------------------------------ 文件角色

# 顺序即优先级：先命中先生效。
_ROLE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('报告', ('报告', 'report')),
    ('明细', ('明细', '台账', '清单', '流水')),
    ('凭证', ('凭证', '发票', '票据', 'voucher', 'invoice')),
    ('合同', ('合同', '协议', 'contract')),
    ('数据', ('数据', '导出', 'data')),
)


def classify_file_role(name: str) -> str:
    """按文件名关键词识别业务角色，识别不出兜底为“资料”。"""
    lowered = name.lower()
    for role, keys in _ROLE_RULES:
        if any(key in name or key in lowered for key in keys):
            return role
    return '资料'


# ------------------------------------------------------------ 期间识别

_PERIOD_YEAR = re.compile(r'(20\d{2})\s*年度')
_PERIOD_QUARTER = re.compile(r'(20\d{2})\s*[Qq]([1-4])(?!\d)')
_PERIOD_MONTH = re.compile(r'(?<!\d)(20\d{2})(0[1-9]|1[0-2])(?!\d)')


def detect_period(name: str) -> str | None:
    """从文件名识别会计期间。

    支持三类保守模式：``2024年度``、``2023Q2``、``202607``（YYYYMM）。
    年度与季度优先于月份，避免“2024年度报告”被误截为月份。
    识别不出返回 None。
    """
    match = _PERIOD_YEAR.search(name)
    if match:
        return f'{match.group(1)}年度'
    match = _PERIOD_QUARTER.search(name)
    if match:
        return f'{match.group(1)}Q{match.group(2)}'
    match = _PERIOD_MONTH.search(name)
    if match:
        return f'{match.group(1)}-{match.group(2)}'
    return None


# ------------------------------------------------------------ 大小格式化

def format_size(size: int) -> str:
    """人类可读的文件大小。"""
    if size < 1024:
        return f'{size} B'
    if size < 1024 ** 2:
        return f'{size / 1024:.1f} KB'
    if size < 1024 ** 3:
        return f'{size / 1024 ** 2:.1f} MB'
    return f'{size / 1024 ** 3:.1f} GB'


# ------------------------------------------------------------ 行视图

@dataclass(frozen=True)
class FileRowView:
    """文件列表行的展示视图：原始字段 + 派生字段。"""

    file_id: str
    name: str
    size: int
    role: str
    period: str | None
    selected: bool
    used_in_tasks: bool


def build_file_rows(files: list[dict], *, selected_ids: set[str],
                    used_ids: set[str]) -> list[FileRowView]:
    """从 store.files() 的原始记录构建展示行。

    ``selected_ids`` 为当前勾选集合，``used_ids`` 为历史任务快照中
    真实使用过的文件 id 集合。
    """
    rows: list[FileRowView] = []
    for item in files:
        name = item['name']
        rows.append(FileRowView(
            file_id=item['id'],
            name=name,
            size=int(item.get('size') or 0),
            role=classify_file_role(name),
            period=detect_period(name),
            selected=item['id'] in selected_ids,
            used_in_tasks=item['id'] in used_ids,
        ))
    return rows


def row_label(view: FileRowView, *, files_map: dict[str, str]) -> str:
    """列表行文本：首行纯文件名（冻结契约），次行角色/期间/大小，末行状态。

    列表默认不显示 hash；``files_map`` 仅为未来扩展保留的查询入口。
    """
    del files_map  # 列表不展示 hash，参数仅保留签名
    meta = f"{view.role} · {view.period or '期间未识别'} · {format_size(view.size)}"
    status_parts: list[str] = []
    status_parts.append('本轮已选' if view.selected else '本轮未选')
    status_parts.append('已用于任务' if view.used_in_tasks else '未使用')
    return f'{view.name}\n{meta}\n{" · ".join(status_parts)}'


# ------------------------------------------------------------ 搜索与过滤

def filter_rows(rows: list[FileRowView], query: str,
                kind: str) -> list[FileRowView]:
    """按文件名子串 + 过滤类别筛选行。

    ``kind``：``all`` 全部、``selected`` 本轮已选、``unused`` 未使用、
    ``used`` 已用于任务。
    """
    query = (query or '').strip()
    result = [row for row in rows if not query or query in row.name]
    if kind == 'selected':
        result = [row for row in result if row.selected]
    elif kind == 'unused':
        result = [row for row in result if not row.used_in_tasks]
    elif kind == 'used':
        result = [row for row in result if row.used_in_tasks]
    return result


# ------------------------------------------------------------ 文件详情

def file_detail_text(view: FileRowView, *, sha256: str, path: str) -> str:
    """文件详情文本：可以展示完整 hash 与路径（非列表场景）。"""
    lines = [
        f'文件名：{view.name}',
        f'角色：{view.role}',
        f'期间：{view.period or "期间未识别"}',
        f'大小：{format_size(view.size)}',
        (f'本轮状态：{"已选" if view.selected else "未选"} · '
         f'{"已用于任务" if view.used_in_tasks else "未使用"}'),
        f'SHA-256：{sha256}',
        f'路径：{path}',
    ]
    return '\n'.join(lines)
