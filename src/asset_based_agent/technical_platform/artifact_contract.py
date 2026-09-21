"""Generation artifact delivery contract: primary deliverables vs internal evidence.

Every successful generation task publishes exactly one primary deliverable
(unless a skill explicitly declares multiple business files). Validation JSON,
feedback notes and staging files stay on disk for gates, recovery and audit,
but they are internal evidence and never appear as user deliverables.
"""
import json
import re
from datetime import date
from pathlib import Path

from .skills import DETAIL, FINANCIAL_BRIEF, HISTORY, WORKFLOW_TO_SKILL

PRIMARY = 'primary'
EVIDENCE = 'validation_evidence'
USER = 'user'
INTERNAL = 'internal'

ROLES = {PRIMARY, EVIDENCE}
VISIBILITIES = {USER, INTERNAL}

# Declared business deliverables per skill: internal standard name -> Chinese label.
# Everything else a skill writes (validation JSON, feedback, staging) is evidence.
SKILL_DELIVERABLES = {
    DETAIL.id: {'detail_workbook.xlsx': '评估明细表'},
    HISTORY.id: {'history_fragment.docx': '工商变更信息'},
    FINANCIAL_BRIEF.id: {'financial_brief.docx': '财务状况简表',
                         'financial_brief.pdf': '财务状况简表（PDF）',
                         'financial_brief.png': '财务状况简表（预览图）'},
    WORKFLOW_TO_SKILL.id: {'office_workflow_contract_validation.json': '工作流契约校验结果'},
}

LEGACY_DELIVERABLE_NAMES = {name for names in SKILL_DELIVERABLES.values() for name in names}

MAX_DISPLAY_NAME = 120
MAX_SUBJECT = 60
FALLBACK_DETAIL_DISPLAY_NAME = '最终评估明细表.xlsx'

_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _validate_display_name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > MAX_DISPLAY_NAME
            or '/' in value or '\\' in value or ':' in value
            or any(ord(char) < 32 for char in value)):
        raise ValueError('Artifact display name is not a safe plain name')


def _declared(item):
    """Return the declared (role, visibility); reject unknown or incomplete metadata."""
    keys = {'role', 'visibility', 'display_name'} & set(item)
    if not keys:
        return None
    if 'role' not in item or 'visibility' not in item:
        raise ValueError('Artifact delivery metadata is incomplete')
    role, visibility = item['role'], item['visibility']
    if role not in ROLES or visibility not in VISIBILITIES:
        raise ValueError('Unknown artifact delivery role or visibility')
    if (role == PRIMARY) != (visibility == USER):
        raise ValueError('Artifact role and visibility are inconsistent')
    if 'display_name' in item:
        _validate_display_name(item['display_name'])
    return role, visibility


def artifact_role(item, skill_id=None):
    declared = _declared(item)
    if declared is not None:
        return declared[0]
    names = SKILL_DELIVERABLES.get(skill_id) if skill_id else None
    if names is not None:
        return PRIMARY if item.get('name') in names else EVIDENCE
    return PRIMARY if item.get('name') in LEGACY_DELIVERABLE_NAMES else EVIDENCE


def artifact_visibility(item, skill_id=None):
    declared = _declared(item)
    if declared is not None:
        return declared[1]
    return USER if artifact_role(item, skill_id) == PRIMARY else INTERNAL


def display_name_of(item):
    """User-facing name: declared display_name, then a safe derivation for legacy
    detail workbooks (read-only lookup beside the stored path), else the raw name."""
    _declared(item)
    if item.get('display_name'):
        return item['display_name']
    if item.get('name') == 'detail_workbook.xlsx':
        path = item.get('path')
        if isinstance(path, str) and path:
            return detail_display_name(Path(path).parent.parent)
    return item.get('name')


def deliverable_label(item):
    """Chinese business label for a declared deliverable name, else None."""
    name = item.get('name')
    for names in SKILL_DELIVERABLES.values():
        if name in names:
            return names[name]
    return None


def user_artifacts(result):
    """(index, artifact) pairs the user may see; declared metadata is validated."""
    return [(index, item) for index, item in enumerate(result.get('artifacts', []))
            if artifact_visibility(item) == USER]


def stamp_artifact(skill_id, name, path, sha256, display_name=None):
    """Register an artifact with its delivery role at generation time."""
    label = SKILL_DELIVERABLES.get(skill_id, {}).get(name)
    item = {'name': name, 'path': str(path), 'sha256': sha256,
            'role': PRIMARY if label else EVIDENCE,
            'visibility': USER if label else INTERNAL}
    if label:
        shown = display_name or (label + Path(name).suffix)
        _validate_display_name(shown)
        item['display_name'] = shown
    return item


def select_primary(result, expected_name):
    """Resolve the unique primary deliverable by identity, never by display title."""
    candidates = [(index, item) for index, item in enumerate(result.get('artifacts', []))
                  if item.get('name') == expected_name and artifact_role(item) == PRIMARY]
    if len(candidates) != 1:
        raise ValueError('Primary artifact is missing or ambiguous')
    return candidates[0]


def _sanitize_subject(text):
    text = _ILLEGAL.sub('', text)
    return re.sub(r'\s+', '', text)[:MAX_SUBJECT]


def detail_display_name(work):
    """Display name from the gated cover-fill report; safe fallback on any doubt."""
    try:
        report = json.loads(
            (Path(work) / 'output' / 'cover_fill_report.json').read_text(encoding='utf-8'))
        if not isinstance(report, dict) or report.get('status') != 'pass':
            return FALLBACK_DETAIL_DISPLAY_NAME
        writes = report.get('writes')
        if not isinstance(writes, dict):
            return FALLBACK_DETAIL_DISPLAY_NAME
        subject, year, month, day = (writes.get('F7'), writes.get('F9'),
                                     writes.get('H9'), writes.get('J9'))
        if not isinstance(subject, str):
            return FALLBACK_DETAIL_DISPLAY_NAME
        subject = _sanitize_subject(subject)
        if not subject or any(type(value) is not int for value in (year, month, day)):
            return FALLBACK_DETAIL_DISPLAY_NAME
        if not 1900 <= year <= 2100:
            return FALLBACK_DETAIL_DISPLAY_NAME
        base = date(year, month, day)  # raises ValueError on impossible dates
        suffix = f'评估明细表（{base:%Y-%m-%d}）.xlsx'
        if len(subject) + len(suffix) > MAX_DISPLAY_NAME:
            subject = subject[:MAX_DISPLAY_NAME - len(suffix)]
        return subject + suffix
    except (OSError, ValueError, TypeError, KeyError):
        return FALLBACK_DETAIL_DISPLAY_NAME
