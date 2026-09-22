"""Model-assisted inventory; model output never authorizes arbitrary files or writes."""

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

from .material_summary import summarize_file
from .skills import digest

ROLES = {'balance_sheet', 'trial_balance', 'journal', 'bank_statement', 'other'}

# Classification evidence (titles and headers) lives in the opening rows, so a
# short per-file excerpt keeps single-call identification fast and reliable.
# (The server reply budget was raised to 8192 tokens; the excerpt bound stays
# to keep prompts small and latency low.)
MAX_FILE_EXCERPT_CHARS = 1500

# Header scan window for deterministic entity/period extraction; statement
# headers (编制单位/日期) live in the opening rows of the first worksheet.
_HEADER_SCAN_ROWS = 6


@dataclass(frozen=True)
class MaterialCandidate:
    artifact_id: str
    role: str
    entity_name: str | None
    period_end: date | None
    evidence: tuple[str, ...]
    confidence: float


@dataclass(frozen=True)
class MaterialResolution:
    status: Literal['resolved', 'waiting_user', 'rejected']
    selected: Mapping[str, str] = field(default_factory=dict)
    candidates: Mapping[str, tuple[MaterialCandidate, ...]] = field(default_factory=dict)
    comparison_artifact_ids: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    # Earlier same-entity periods of non-statement roles: audit trail only,
    # never pipeline comparison input.
    reference_artifact_ids: tuple[str, ...] = ()


def statement_metadata(path):
    """Read-only entity/period extraction from a statement workbook header.

    Returns (entity_name, period_end, evidence); any component may be None.
    Only workbook body text is used — never the file name.
    """
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    entity, period = None, None
    evidence = []
    if Path(path).suffix.lower() == '.xls':
        from .xls_support import xls_header_values
        values = xls_header_values(path, _HEADER_SCAN_ROWS)
        if values is None:
            return None, None, ('工作簿不可读取',)
    else:
        try:
            book = load_workbook(path, read_only=True, data_only=True)
        except Exception:  # noqa: BLE001 - unreadable workbook means unidentifiable
            return None, None, ('工作簿不可读取',)
        try:
            sheet = book['资产负债表'] if '资产负债表' in book.sheetnames else book.worksheets[0]
            values = [str(cell.value).strip() for row in sheet.iter_rows(max_row=_HEADER_SCAN_ROWS)
                      for cell in row if cell.value not in (None, '')]
        finally:
            book.close()
    unit = next((item for item in values if '编制单位' in item or '单位名称' in item), '')
    if unit:
        name = re.sub(r'.*(?:编制单位|单位名称)[:：]?\s*', '', unit).strip()
        if name and not re.search(r'\d{4}年\d{1,2}月', name) and name != '元':
            entity = name
            evidence.append(f'表头编制单位：{name}')
    text = ' '.join(values)
    match = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日', text)
    if match:
        period = date(*map(int, match.groups()))
        evidence.append(f'表头报表日期：{period.isoformat()}')
    if not evidence:
        evidence.append('表头缺少编制单位或报表日期')
    return entity, period, tuple(evidence)


def _validate_assignments(plan, files):
    assignments = plan.get('assignments')
    if not isinstance(assignments, list):
        raise ValueError('资料识别结果无效，请重试')  # noqa: TRY004 - user-facing boundary
    known = {item['id'] for item in files}
    seen = set()
    parsed = []
    for item in assignments:
        identity, role = item.get('file_id'), item.get('role')
        if identity not in known or identity in seen or role not in ROLES:
            raise ValueError('资料识别包含未知或重复文件，请重新分析')
        seen.add(identity)
        parsed.append((identity, role, str(item.get('reason') or '')))
    if seen != known:
        raise ValueError('资料识别遗漏文件，请重新分析')
    return parsed


def resolve_materials(plan, files):
    """Split classification from disambiguation: roles may hold many candidates.

    Same-entity multi-period statements resolve deterministically to the latest
    period with earlier ones kept as comparison material. Anything ambiguous
    returns structured questions (waiting_user) instead of a flat error.
    """
    parsed = _validate_assignments(plan, files)
    by_id = {item['id']: item for item in files}
    groups = {}
    for identity, role, reason in parsed:
        if role != 'other':
            groups.setdefault(role, []).append((identity, reason))

    selected = {}
    candidates = {}
    comparison = []
    reference = []
    questions = []
    reasons = []
    for role, members in groups.items():
        if len(members) == 1:
            identity, reason = members[0]
            selected[role] = identity
            candidates[role] = (MaterialCandidate(identity, role, None, None, (reason,), 1.0),)
            continue
        if role == 'balance_sheet':
            info = []
            for identity, reason in members:
                path = by_id[identity].get('path')
                if path:
                    entity, period, evidence = statement_metadata(path)
                else:
                    entity, period, evidence = None, None, ('缺少可读取的文件路径',)
                info.append((identity, entity, period, evidence, reason))
            entities = {entity for _, entity, _, _, _ in info if entity}
            names = {identity: by_id[identity].get('name', identity) for identity, *_ in info}
            if len(entities) > 1:
                questions.append('检测到 ' + '、'.join(sorted(entities))
                                 + ' 两组报表，请选择本轮使用的主体')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            if any(entity is None for _, entity, _, _, _ in info):
                questions.append('部分资产负债表无法从正文识别编制单位（涉及：'
                                 + '、'.join(names[i] for i, e, _, _, _ in info if e is None)
                                 + '），请说明本轮使用的主体及对应文件')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            if any(period is None for _, _, period, _, _ in info):
                questions.append('部分资产负债表无法从正文识别报表期间（涉及：'
                                 + '、'.join(names[i] for i, _, p, _, _ in info if p is None)
                                 + '），请说明各文件对应的期间')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            periods = [period for _, _, period, _, _ in info]
            if len(set(periods)) != len(periods):
                dupes = sorted({p.isoformat() for p in periods if periods.count(p) > 1})
                questions.append('同一主体同一期间（' + '、'.join(dupes)
                                 + '）存在多份报表版本，请确认以哪一份为准')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            ordered = sorted(info, key=lambda item: item[2])
            chosen = ordered[-1]
            selected[role] = chosen[0]
            comparison.extend(i for i, *_ in ordered[:-1])
            entity = chosen[1]
            reasons.append('同一主体（' + entity + '）识别到 ' + str(len(ordered))
                           + ' 期资产负债表，按报表正文期间选择最新一期 '
                           + chosen[2].isoformat() + '（' + names[chosen[0]]
                           + '）作为主输入，其余期间保留为历史对比资料')
            candidates[role] = tuple(
                MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in ordered)
            continue
        if role in ('trial_balance', 'journal'):
            label = '试算表' if role == 'trial_balance' else '序时账'
            info = []
            for identity, reason in members:
                path = by_id[identity].get('path')
                if path:
                    summary = summarize_file(path, identity,
                                             by_id[identity].get('name'))
                    entity = summary['entity_name']
                    period = (date.fromisoformat(summary['period_end'])
                              if summary['period_end'] else None)
                    evidence = (tuple(summary['header_evidence'][:6])
                                + tuple(summary['warnings']))
                else:
                    entity, period, evidence = None, None, ('缺少可读取的文件路径',)
                info.append((identity, entity, period, evidence, reason))
            entities = {entity for _, entity, _, _, _ in info if entity}
            names = {identity: by_id[identity].get('name', identity) for identity, *_ in info}
            if len(entities) > 1:
                questions.append('检测到 ' + '、'.join(sorted(entities))
                                 + ' 两组' + label + '，请选择本轮使用的主体')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            if any(entity is None for _, entity, _, _, _ in info):
                questions.append('部分' + label + '无法从正文识别主体（涉及：'
                                 + '、'.join(names[i] for i, e, _, _, _ in info if e is None)
                                 + '），请说明本轮使用的主体及对应文件')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            if any(period is None for _, _, period, _, _ in info):
                questions.append('部分' + label + '无法从正文识别期间（涉及：'
                                 + '、'.join(names[i] for i, _, p, _, _ in info if p is None)
                                 + '），请说明各文件对应的期间')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            periods = [period for _, _, period, _, _ in info]
            if len(set(periods)) != len(periods):
                dupes = sorted({p.isoformat() for p in periods if periods.count(p) > 1})
                questions.append('同一主体同一期间（' + '、'.join(dupes)
                                 + '）存在多份' + label + '版本，请确认以哪一份为准')
                candidates[role] = tuple(
                    MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in info)
                continue
            ordered = sorted(info, key=lambda item: item[2])
            chosen = ordered[-1]
            selected[role] = chosen[0]
            reference.extend(i for i, *_ in ordered[:-1])
            reasons.append('同一主体（' + chosen[1] + '）识别到 ' + str(len(ordered))
                           + ' 期' + label + '，按表内期间选择最新一期 '
                           + chosen[2].isoformat() + '（' + names[chosen[0]]
                           + '）作为主输入，其余期间保留为历史参考（不作为对比报表）')
            candidates[role] = tuple(
                MaterialCandidate(i, role, e, p, ev + (r,), 1.0) for i, e, p, ev, r in ordered)
            continue
        # Duplicated non-statement roles cannot be disambiguated deterministically.
        questions.append('识别到多份同类资料（' + role + '：'
                         + '、'.join(by_id[i].get('name', i) for i, _ in members)
                         + '），请说明本轮使用哪一份')
        candidates[role] = tuple(
            MaterialCandidate(i, role, None, None, (r,), 1.0) for i, r in members)

    # Cross-check the selected TB/TBD pair: in-table entity and period must
    # agree before the two are treated as one dataset.
    pair = {}
    for role in ('trial_balance', 'journal'):
        identity = selected.get(role)
        if not identity:
            continue
        path = by_id[identity].get('path')
        if path:
            summary = summarize_file(path, identity, by_id[identity].get('name'))
            pair[role] = (summary['entity_name'], summary['period_end'])
    if len(pair) == 2:
        tb_entity, tb_period = pair['trial_balance']
        tbd_entity, tbd_period = pair['journal']
        if tb_entity and tbd_entity and tb_entity != tbd_entity:
            questions.append('试算表主体（' + tb_entity + '）与序时账主体（' + tbd_entity
                             + '）不一致，请确认本轮使用的主体')
        elif tb_period and tbd_period and tb_period != tbd_period:
            questions.append('最新试算表期间（' + tb_period + '）与序时账最新期间（'
                             + tbd_period + '）不一致，请确认本轮使用的期间')
        elif tb_period and tbd_period:
            reasons.append('最新试算表与序时账期间一致（' + tb_period + '），自动配对')
    if questions:
        return MaterialResolution('waiting_user', dict(selected), candidates, (),
                                  tuple(questions), tuple(reasons),
                                  reference_artifact_ids=tuple(reference))
    return MaterialResolution('resolved', selected, candidates, tuple(comparison), (),
                              tuple(reasons), reference_artifact_ids=tuple(reference))


def resolve_roles(plan, files):
    """Compatibility wrapper: single-value role mapping for legacy callers."""
    resolution = resolve_materials(plan, files)
    if resolution.status != 'resolved':
        raise ValueError('存在多份同类资料，需要先确认本轮使用的主体和期间')
    return dict(resolution.selected)


def resolution_snapshot(resolution):
    """JSON-serializable audit/persist form of a MaterialResolution."""
    candidates = {
        role: [{'artifact_id': c.artifact_id, 'role': c.role,
                'entity_name': c.entity_name,
                'period_end': c.period_end.isoformat() if c.period_end else None,
                'evidence': list(c.evidence), 'confidence': c.confidence}
               for c in members]
        for role, members in resolution.candidates.items()
    }
    return {'status': resolution.status, 'selected': dict(resolution.selected),
            'candidates': candidates,
            'comparison_artifact_ids': list(resolution.comparison_artifact_ids),
            'reference_artifact_ids': list(resolution.reference_artifact_ids),
            'questions': list(resolution.questions), 'reasons': list(resolution.reasons)}


def apply_resolution_override(override, files, stored):
    """Rebuild a resolution from the user's clarification without a model call.

    The override must stay inside the persisted candidate set so a resumed run
    can never widen the file scope beyond what the model already classified.
    """
    if not isinstance(override, dict) or not override:
        raise ValueError('澄清结果无效，请重新提交')
    known = {item['id'] for item in files}
    candidates = stored.get('candidates', {})
    selected = {}
    for role, identity in override.items():
        if role not in ROLES - {'other'} or identity not in known:
            raise ValueError('澄清结果超出本轮资料范围，请重新提交')
        pool = {c['artifact_id'] for c in candidates.get(role, [])}
        if pool and identity not in pool:
            raise ValueError('澄清结果与已识别资料不一致，请重新提交')
        selected[role] = identity
    selected_entity = selected_period = None
    for c in candidates.get('balance_sheet', []):
        if c['artifact_id'] == selected.get('balance_sheet'):
            selected_entity, selected_period = c.get('entity_name'), c.get('period_end')
    # Only same-entity earlier periods are comparison material; a rejected
    # other-entity statement or a superseded same-period version is not.
    comparison = tuple(
        c['artifact_id'] for c in candidates.get('balance_sheet', [])
        if c['artifact_id'] != selected.get('balance_sheet')
        and selected_entity is not None and c.get('entity_name') == selected_entity
        and c.get('period_end') is not None and c['period_end'] != selected_period)
    resolved_candidates = {
        role: tuple(MaterialCandidate(c['artifact_id'], c['role'], c.get('entity_name'),
                                      date.fromisoformat(c['period_end']) if c.get('period_end') else None,
                                      tuple(c.get('evidence', ())), c.get('confidence', 1.0))
                    for c in members)
        for role, members in candidates.items()}
    return MaterialResolution('resolved', selected, resolved_candidates, comparison, (),
                              ('已按用户澄清确定本轮主体与期间。',))


class MaterialAnalysisProvider:
    def __init__(self, client, model_id, skill_instructions):
        self.client, self.model_id = client, model_id
        self.skill_instructions = skill_instructions

    def analyze(self, files, run_id, cancel, progress):
        from ..report_review_app.domain.models import SourceFile
        from ..report_review_app.services.document_extraction_service import (
            DocumentExtractionService,
        )
        from ..report_review_app.services.file_role_service import classify_file_role
        from ..report_review_app.services.privacy_filter import PrivacyChunkSelector
        from ..report_review_app.services.task_cancellation import (
            TaskCancelled,
            cancellable_call,
        )

        documents = []
        for item in files:
            if cancel.is_set():
                raise TaskCancelled('资料分析已取消')
            path = Path(item['path'])
            if digest(path) != item['sha256']:
                raise ValueError('资料已变化，请重新添加')
            progress(f'正在只读分析资料：{item["name"]}')
            source = SourceFile(file_id=item['id'], original_name=item['name'], extension=path.suffix.lower(),
                                sha256=item['sha256'], size_bytes=path.stat().st_size, round_number=1,
                                original_path=str(path), role=classify_file_role(path))
            documents.append(cancellable_call(lambda source=source: DocumentExtractionService().extract(source), cancel))
        batches = PrivacyChunkSelector().build_batches(documents)
        texts = {item['id']: [] for item in files}
        for batch in batches:
            for chunk in batch.chunks:
                texts[chunk.source_file_id].append(chunk.text)
        # Bounded visible excerpts only; no paths, binary originals or hidden sheets.
        payload_files = [{'file_id': item['id'], 'name': item['name'],
                          'text': ('（用户指定：本文件仅作参考资料，不作为填报依据。）\n'
                                   if item.get('user_role') == 'reference' else '')
                          + '\n'.join(texts[item['id']])[:MAX_FILE_EXCERPT_CHARS]}
                         for item in files]
        if cancel.is_set():
            raise TaskCancelled('资料分析已取消')
        progress('正在联网验证并调用模型识别资料；识别不会编造缺失数据。')
        payload = {'model_id': self.model_id, 'request_id': 'MATERIAL-' + run_id, 'files': payload_files}
        cancellable = getattr(self.client, 'analyze_materials_cancellable', None)

        def call_model():
            return (cancellable(payload, cancel) if callable(cancellable)
                    else self.client.analyze_materials(payload))

        from ..report_review_app.services.remote_auth_service import (
            RemoteAuthenticationError,
        )
        attempts = 0
        while True:
            try:
                plan = cancellable_call(call_model, cancel)
                break
            except RemoteAuthenticationError as exc:
                # The server explicitly asks for a retry when the model reply was
                # truncated or malformed; auth/session failures must not retry.
                attempts += 1
                if attempts >= 3 or '资料识别结果不完整' not in str(exc) or cancel.is_set():
                    raise
                progress(f'识别结果不完整，正在重试（第 {attempts} 次）。')
        return resolve_materials(plan, files), plan
