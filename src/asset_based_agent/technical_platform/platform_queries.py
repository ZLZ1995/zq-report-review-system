"""K05：平台状态查询的确定性回答 + 文件只读问答的受限可见摘要。

意图（咨询还是执行）始终由结构化模型判断；本模块只在模型已判为咨询之后，
决定"平台查询用哪份真实数据回答"以及"文件问答可以读哪些内容"：
平台数据永远来自本地数据库/注册表，不让模型猜测；文件问答只读取本轮
明确选择或明确提及的文件，只取可见内容的受限摘要，不发送绝对路径、
隐藏工作表或二进制内容，绝不写回原件。
"""
from __future__ import annotations

from pathlib import Path

from .release_info import CLIENT_VERSION
from .turn_normalizer import normalize_text

_MAX_FILES = 3
_FILE_BUDGET = 3000
_MAX_SHEETS = 3
_MAX_ROWS = 12
_MAX_COLS = 8
_CELL_LIMIT = 24

# 文件内容指代信号：仅用于决定"咨询回答是否需要可见摘要落地"，
# 不用于判断咨询/执行意图（意图已由结构化模型裁决）。
_FILE_DEIXIS = ('这份', '这个文件', '这两个文件', '这几个文件', '该文件',
                '表中', '表里', '报告里', '文档里', '文件里')


def _compact(prompt: str) -> str:
    return normalize_text(prompt).replace(' ', '').casefold()


def platform_answer(store, session_id: str, prompt: str, *, client=None) -> str | None:
    """平台状态查询命中时返回确定性回答；未命中返回 None（用模型回答）。"""
    text = _compact(prompt)
    if '文件' in text and any(q in text for q in ('几个', '多少', '哪些', '列表', '有什么')):
        return _files_answer(store, session_id)
    if ('skill' in text or '技能' in text) and any(
            q in text for q in ('哪些', '什么', '列表', '装了', '安装', '版本', '几个', '多少')):
        return _skills_answer(store)
    if '任务' in text and any(q in text for q in ('状态', '完成', '进度', '怎么样', '如何', '结果')):
        return _task_answer(store, session_id)
    if '版本' in text and any(q in text for q in ('客户端', '服务端', '平台', '当前', '现在')):
        return _version_answer(client)
    if '项目' in text and '文件' not in text and any(
            q in text for q in ('哪些', '列表', '几个', '多少')):
        return _projects_answer(store)
    return None


def _files_answer(store, session_id: str) -> str:
    session = store.session(session_id)
    files = store.files(session['project'])
    if not files:
        return '当前项目还没有任何文件；可以先通过"添加文件"导入资料。'
    names = [item['name'] for item in files]
    shown = '、'.join(names[:20])
    suffix = f'等共 {len(names)} 个。' if len(names) > 20 else '。'
    return f'当前项目共有 {len(names)} 个文件：{shown}{suffix}'


def _skills_answer(store) -> str:
    from .skill_installation import SkillInstallation
    from .skills import BUILTINS
    rows = SkillInstallation(store).list_versions()
    builtin = '、'.join(f'{spec.name} {spec.version}' for spec in BUILTINS)
    if not rows:
        return f'当前没有安装额外的 Skill；内置能力：{builtin}。'
    items = '、'.join(
        f"{row['name']} {row['version']}（{'启用' if row['enabled'] else '停用'}）" for row in rows)
    return f'已安装 {len(rows)} 个 Skill 版本：{items}。另有内置能力：{builtin}。'


def _task_answer(store, session_id: str) -> str:
    from .conversation_state import ConversationState
    state = ConversationState(store).read(session_id)
    if state['task_id'] and state['question'] and not state['cancelled']:
        return '当前有一个任务正在等待你补充信息：' + str(state['question']['text'])
    if state['task_id'] and not state['cancelled']:
        return '当前有一个任务正在理解或等待确认，尚未开始执行。'
    runs = store.runs(session_id)
    if runs:
        latest = runs[-1]
        label = {'succeeded': '已成功完成', 'failed': '执行失败',
                 'cancelled': '已取消', 'running': '仍在执行中'}.get(latest['state'], latest['state'])
        return f'当前没有待处理的任务；上一个任务{label}。'
    return '当前没有待处理或历史记录中的任务。'


def _version_answer(client) -> str:
    from .skills import REVIEW
    base = f'客户端 {CLIENT_VERSION} · 审核 Skill {REVIEW.version}'
    probe = getattr(client, 'server_build_info', None)
    if callable(probe):
        try:
            info = probe()
        except Exception:  # noqa: BLE001 - 版本查询失败降级为仅客户端信息
            info = None
        if info and info.get('build_sha'):
            return base + f'；服务端 build {str(info["build_sha"])[:12]}' \
                          f'（协议 schema {info.get("schema_version")}）。'
    return base + '；服务端版本需在连接成功后查看。'


def _projects_answer(store) -> str:
    projects = store.projects()
    if not projects:
        return '当前账号下还没有项目。'
    names = '、'.join(item['name'] for item in projects[:20])
    suffix = f'等共 {len(projects)} 个。' if len(projects) > 20 else '。'
    return f'当前账号共有 {len(projects)} 个项目：{names}{suffix}'


def pointed_file_ids(store, project_id: str, prompt: str, selected_ids) -> list[str]:
    """本轮明确指向的文件：按名称提及的文件，加上存在内容指代时的已选文件。"""
    available = store.files(project_id)
    mentioned = [item['id'] for item in available if item['name'] in prompt]
    pointed = list(dict.fromkeys(mentioned))
    if any(token in _compact(prompt) for token in _FILE_DEIXIS):
        selected = {item['id'] for item in available if item['id'] in set(selected_ids)}
        pointed = list(dict.fromkeys([*pointed, *selected]))
    return pointed[:_MAX_FILES]


def visible_summaries(store, project_id: str, file_ids) -> list[dict]:
    """只读可见摘要：仅名称 + 可见内容片段；绝不包含绝对路径或隐藏内容。"""
    available = {item['id']: item for item in store.files(project_id)}
    summaries = []
    for file_id in list(file_ids)[:_MAX_FILES]:
        item = available.get(file_id)
        if item is None:
            continue
        summary = _summarize(Path(item['path']), item['name'])
        summaries.append({'name': item['name'], 'summary': summary})
    return summaries


def _summarize(path: Path, name: str) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in ('.xlsx', '.xlsm'):
            return _xlsx_summary(path)
        if suffix in ('.csv', '.txt', '.md'):
            return path.read_text(encoding='utf-8', errors='replace')[:2000]
        if suffix == '.docx':
            return _docx_summary(path)
    except (OSError, ValueError):
        return '（文件暂时无法读取，未纳入回答依据。）'
    return f'（{suffix or "该"} 类型暂不支持只读预览，未纳入回答依据。）'


def _xlsx_summary(path: Path) -> str:
    from openpyxl import load_workbook
    book = load_workbook(path, read_only=True, data_only=True)
    parts, budget = [], _FILE_BUDGET
    try:
        sheets = [ws for ws in book.worksheets if ws.sheet_state == 'visible']
        for sheet in sheets[:_MAX_SHEETS]:
            rows = []
            for row in sheet.iter_rows(min_row=1, max_row=_MAX_ROWS, max_col=_MAX_COLS,
                                       values_only=True):
                cells = [str(value)[:_CELL_LIMIT] if value is not None else '' for value in row]
                if any(cells):
                    rows.append(' | '.join(cells).rstrip(' |'))
            part = f'工作表“{sheet.title}”：\n' + '\n'.join(rows)
            parts.append(part[:budget])
            budget -= len(parts[-1])
            if budget <= 0:
                break
    finally:
        book.close()
    if not parts:
        return '（工作簿没有可见工作表或可见内容。）'
    return '\n'.join(parts)


def _docx_summary(path: Path) -> str:
    from docx import Document
    document = Document(path)
    lines = [p.text for p in document.paragraphs[:40] if p.text.strip()]
    return '\n'.join(lines)[:2000] or '（文档没有可见段落文本。）'
