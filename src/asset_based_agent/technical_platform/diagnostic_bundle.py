"""Diagnostic bundle: complete trace, privacy-safe by default.

The trace carries every identifier needed to locate a fault — task, turn,
plan, node and attempt IDs, channel status, first-response latency, retry
reasons, manifest ID, skill/rules/template hashes, resource waits, the
Office/WPS choice, browser origin, server job ID, billing status and
artifact IDs/hashes/verification states. Tokens and fees never enter the
schema. Document bodies, passwords, cookies, API keys and full client paths
are redacted or excluded before preview and export; export refuses any
bundle that still scans positive for sensitive content.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..agent_contracts import Identifier, Record

SENSITIVE_PATTERNS: dict[str, re.Pattern] = {
    'password': re.compile(r'(?i)\b(?:password|passwd|pwd)\s*[:=]\s*\S+'),
    'cookie': re.compile(r'(?i)\bcookie\s*[:=]\s*\S+'),
    'api_key': re.compile(r'(?i)\b(?:api[-_ ]?key|secret|token)\s*[:=]\s*\S+'),
    'bearer': re.compile(r'(?i)\bbearer\s+[A-Za-z0-9._%-]+'),
    'client_path': re.compile(r'[A-Za-z]:\\Users\\[^\s]+'),
}

DOCUMENT_BODY_KEYS = ('content', 'body', 'document_text', 'full_text')


def redact_text(text: str) -> str:
    for label, pattern in SENSITIVE_PATTERNS.items():
        if label == 'client_path':
            text = pattern.sub('<client-path>', text)
        else:
            text = pattern.sub(f'<redacted:{label}>', text)
    return text


def scan_sensitive(text: str) -> list[str]:
    return sorted(label for label, pattern in SENSITIVE_PATTERNS.items()
                  if pattern.search(text))


class ResourceWait(Record):
    resource: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=500)
    duration_ms: int = Field(ge=0)


class ArtifactDiagnostics(Record):
    artifact_id: Identifier
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    verification: Literal['passed', 'failed', 'pending']


class DiagnosticTrace(Record):
    """Fault-localization trace. Tokens and fees have no fields here."""
    task_id: Identifier
    turn_id: Identifier
    plan_id: Identifier
    node_id: Identifier | None = None
    attempt_id: Identifier | None = None
    channel_status: str = Field(min_length=1, max_length=64)
    first_response_latency_ms: int | None = Field(default=None, ge=0)
    retry_reasons: tuple[str, ...] = ()
    manifest_id: Identifier | None = None
    skill_hash: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    rules_hash: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    template_hash: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    resource_waits: tuple[ResourceWait, ...] = ()
    office_backend: Literal['office', 'wps', 'none'] = 'none'
    browser_origin: str | None = Field(default=None, max_length=256)
    server_job_id: Identifier | None = None
    billing_status: Literal['settled_charged', 'settled_unpaid',
                            'not_applicable', 'unknown'] = 'unknown'
    artifacts: tuple[ArtifactDiagnostics, ...] = ()


def _redacted_events(journal, run_id) -> list[dict]:
    events = []
    for event in journal.events(run_id):
        payload = {key: redact_text(value)
                   for key, value in event.payload.items()
                   if key not in DOCUMENT_BODY_KEYS}
        events.append({'seq': event.seq, 'node_id': event.node_id,
                       'type': event.type, 'at': event.at,
                       'payload': payload})
    return events


def build_bundle(trace: DiagnosticTrace, *, journal=None, run_id=None,
                 notes: str = '') -> dict:
    """Assemble the bundle; document body keys are dropped, text redacted."""
    bundle = {'schema': 'diagnostic-bundle/v1',
              'trace': trace.model_dump(mode='json'),
              'events': _redacted_events(journal, run_id)
              if journal is not None and run_id is not None else [],
              'notes': redact_text(notes)}
    return bundle


def preview_bundle(bundle: dict) -> str:
    """Human-readable preview shown before export."""
    return json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True)


def export_bundle(bundle: dict, path) -> Path:
    """Refuse to write any bundle that still scans positive."""
    text = preview_bundle(bundle)
    hits = scan_sensitive(text)
    if hits:
        raise ValueError(
            f'诊断包含敏感信息（{", ".join(hits)}），已拒绝导出')
    target = Path(path)
    target.write_text(text, encoding='utf-8')
    return target
