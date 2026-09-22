"""S12 成果交付与任务历史（纯逻辑层）。

铁律：
- 成果/任务数据全部来自 store 真实 runs 记录，不得臆造；
- 未知状态显示“状态待核对”，绝不显示“失败”；
- 损坏的 result JSON 跳过该 run 的成果，不崩溃；
- 内部证据文件（visibility=internal）不出现在成果列表。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# ------------------------------------------------------------ 状态文案

_STATE_LABELS = {
    'queued': '排队中',
    'running': '运行中',
    'validating': '校验中',
    'waiting_user': '等待补充',
    'succeeded': '已成功',
    'failed': '失败',
    'cancelled': '已取消',
    'interrupted': '已中断',
}


def state_label(state: str | None) -> str:
    """真实状态的用户文案；未知状态显示“状态待核对”，绝不显示失败。"""
    return _STATE_LABELS.get(state or '', '状态待核对')


_KIND_LABELS = {
    'generation': '生成成果',
    'review': '审核报告',
    'review_annotation': '问题批注副本',
}


# ------------------------------------------------------------ 成果条目

@dataclass(frozen=True)
class ArtifactEntry:
    """一条用户可见成果：来源 run + 展示名 + 真实路径。"""

    run_id: str
    session_id: str
    index: int | None  # result['artifacts'] 下标；导出的报告/批注为 None
    name: str
    path: str
    kind: str
    state: str
    created: str
    label: str | None


def _generation_entries(run: dict, result: dict) -> list[ArtifactEntry]:
    from .artifact_contract import deliverable_label, display_name_of, user_artifacts
    entries: list[ArtifactEntry] = []
    for index, item in user_artifacts(result):
        path = item.get('path')
        if not isinstance(path, str) or not path:
            continue
        entries.append(ArtifactEntry(
            run_id=run['id'], session_id=run['session'], index=index,
            name=display_name_of(item), path=path, kind='generation',
            state=run['state'], created=run['created'],
            label=deliverable_label(item)))
    return entries


def _review_entries(run: dict, result: dict) -> list[ArtifactEntry]:
    entries: list[ArtifactEntry] = []
    report = result.get('exported_report')
    if isinstance(report, str) and report:
        entries.append(ArtifactEntry(
            run_id=run['id'], session_id=run['session'], index=None,
            name=Path(report).name, path=report, kind='review',
            state=run['state'], created=run['created'], label='标准审核报告'))
    for batch in result.get('annotations') or []:
        for path in batch.get('files') or []:
            if isinstance(path, str) and path:
                entries.append(ArtifactEntry(
                    run_id=run['id'], session_id=run['session'], index=None,
                    name=Path(path).name, path=path, kind='review_annotation',
                    state=run['state'], created=run['created'], label='问题批注副本'))
    return entries


def collect_artifacts(store, project_id: str) -> list[ArtifactEntry]:
    """项目全部会话历史 run 的用户可见成果（历史成果可访问）。

    损坏/无结果的 run 跳过其成果；组合计划（plan）的步骤成果是独立 run，
    会随各自 run 记录自然出现。
    """
    entries: list[ArtifactEntry] = []
    for session in store.sessions(project_id):
        for run in store.runs(session['id']):
            try:
                result = json.loads(run['result'] or '{}')
            except (TypeError, ValueError):
                continue
            if not isinstance(result, dict):
                continue
            try:
                if result.get('kind') == 'generation':
                    entries.extend(_generation_entries(run, result))
                elif result.get('kind') == 'review':
                    entries.extend(_review_entries(run, result))
            except (ValueError, KeyError, TypeError):
                continue
    return entries


def artifact_row_text(entry: ArtifactEntry) -> str:
    """成果列表行：首行展示名，次行生成说明（类型 · 任务短 id · 状态 · 时间）。"""
    kind_label = entry.label or _KIND_LABELS.get(entry.kind, '成果')
    return (f'{entry.name}\n'
            f'{kind_label} · 任务 {entry.run_id[:9]} · '
            f'{state_label(entry.state)} · {entry.created}')


def artifact_detail_text(entry: ArtifactEntry) -> str:
    """成果详情：完整路径与完整任务 ID。"""
    return '\n'.join([
        f'文件名：{entry.name}',
        f'类型：{entry.label or _KIND_LABELS.get(entry.kind, "成果")}',
        f'状态：{state_label(entry.state)}',
        f'生成时间：{entry.created}',
        f'任务 ID：{entry.run_id}',
        f'路径：{entry.path}',
    ])


# ------------------------------------------------------------ 任务历史

def task_row_text(run: dict, snapshot: dict) -> str:
    """任务列表行：状态 · 任务短 id + 请求摘要 · 创建时间。"""
    request = snapshot.get('user_request') or snapshot.get('prompt') or ''
    request = str(request).strip().replace('\n', ' ')[:40]
    summary = request or '（无请求摘要）'
    return (f'{state_label(run["state"])} · 任务 {run["id"][:9]}\n'
            f'{summary} · {run["created"]}')


def task_detail_text(run: dict, snapshot: dict,
                     result: dict | None = None) -> str:
    """任务详情：完整任务 ID / operation ID / 会话 / 状态 / 时间。"""
    operation_id = (snapshot.get('operation_id')
                    or (result or {}).get('operation_id')
                    or '未记录（旧链路任务）')
    return '\n'.join([
        f'任务 ID：{run["id"]}',
        f'Operation ID：{operation_id}',
        f'会话：{run["session"]}',
        f'状态：{state_label(run["state"])}',
        f'创建时间：{run["created"]}',
    ])
