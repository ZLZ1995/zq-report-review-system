"""G10 诊断包：Trace 完整性、脱敏、导出预览与敏感扫描。

验收：Trace 覆盖要求的全部字段；诊断包默认排除文档正文、密码、Cookie、
API Key 和完整客户路径；导出前允许预览；客户端不得显示 Token 和费用；
敏感信息扫描为 0 命中。
"""
import pytest
from pydantic import ValidationError


def make_trace(**overrides):
    from asset_based_agent.technical_platform.diagnostic_bundle import DiagnosticTrace
    base = {'task_id': 't1', 'turn_id': 'turn-1', 'plan_id': 'p1',
            'node_id': 's1', 'attempt_id': 'attempt-1',
            'channel_status': 'connected', 'first_response_latency_ms': 820,
            'retry_reasons': ('TimeoutError',), 'manifest_id': 'm1',
            'skill_hash': 'a' * 64, 'rules_hash': 'b' * 64,
            'template_hash': 'c' * 64,
            'office_backend': 'office', 'browser_origin': 'https://oa.example.com',
            'server_job_id': 'job-1', 'billing_status': 'settled_charged'}
    base.update(overrides)
    return DiagnosticTrace(**base)


def test_trace_covers_required_fields():
    trace = make_trace()
    dump = trace.model_dump()
    for field in ('task_id', 'turn_id', 'plan_id', 'node_id', 'attempt_id',
                  'channel_status', 'first_response_latency_ms',
                  'retry_reasons', 'manifest_id', 'skill_hash', 'rules_hash',
                  'template_hash', 'resource_waits', 'office_backend',
                  'browser_origin', 'server_job_id', 'billing_status',
                  'artifacts'):
        assert field in dump, field


def test_trace_records_resource_waits_and_artifacts():
    from asset_based_agent.technical_platform.diagnostic_bundle import (
        ArtifactDiagnostics,
        ResourceWait,
    )
    trace = make_trace(
        resource_waits=(ResourceWait(resource='workbook:f1',
                                     reason='被其他任务占用',
                                     duration_ms=300),),
        artifacts=(ArtifactDiagnostics(artifact_id='a1', sha256='d' * 64,
                                       verification='passed'),))
    assert trace.resource_waits[0].resource == 'workbook:f1'
    assert trace.artifacts[0].verification == 'passed'


def test_trace_rejects_smuggled_token_or_fee():
    with pytest.raises(ValidationError):
        make_trace(api_token='sk-secret')
    with pytest.raises(ValidationError):
        make_trace(fee_yuan=12.5)


def test_billing_status_vocabulary():
    with pytest.raises(ValidationError):
        make_trace(billing_status='免费')


def test_redact_password_cookie_apikey():
    from asset_based_agent.technical_platform.diagnostic_bundle import redact_text
    dirty = 'password: hunter2 cookie=sessionid%3Dabc api_key: sk-123456'
    clean = redact_text(dirty)
    assert 'hunter2' not in clean
    assert 'sessionid' not in clean
    assert 'sk-123456' not in clean
    assert clean.count('<redacted') == 3


def test_redact_bearer_token():
    from asset_based_agent.technical_platform.diagnostic_bundle import redact_text
    assert 'eyJhbGci' not in redact_text('Authorization: Bearer eyJhbGci.xyz')


def test_redact_client_full_path():
    from asset_based_agent.technical_platform.diagnostic_bundle import redact_text
    dirty = r'读取 C:\Users\alice\客户资料\资产负债表.xlsx 失败'
    clean = redact_text(dirty)
    assert 'alice' not in clean
    assert '客户资料' not in clean
    assert '<client-path>' in clean


def test_bundle_excludes_document_body(tmp_path):
    from asset_based_agent.technical_platform.diagnostic_bundle import build_bundle
    from asset_based_agent.technical_platform.workflow_journal import WorkflowJournal
    journal = WorkflowJournal(tmp_path / 'j.jsonl')
    journal.append(run_id='r1', node_id='s1', type='node_progress',
                   at='2026-09-18T10:00:01Z',
                   payload={'channel': 'parse', 'message': '解析中',
                            'content': '客户合同正文机密段落'})
    bundle = build_bundle(make_trace(), journal=journal, run_id='r1')
    assert '客户合同正文机密段落' not in str(bundle)
    assert '解析中' in str(bundle)


def test_preview_before_export():
    from asset_based_agent.technical_platform.diagnostic_bundle import (
        build_bundle,
        preview_bundle,
    )
    preview = preview_bundle(build_bundle(make_trace()))
    assert isinstance(preview, str)
    assert 't1' in preview
    assert 'settled_charged' in preview


def test_scan_sensitive_reports_labels():
    from asset_based_agent.technical_platform.diagnostic_bundle import scan_sensitive
    hits = scan_sensitive('password: abc api_key=zzz')
    assert 'password' in hits
    assert 'api_key' in hits
    assert scan_sensitive('一切正常的日志') == []


def test_export_clean_bundle_writes_file(tmp_path):
    from asset_based_agent.technical_platform.diagnostic_bundle import (
        build_bundle,
        export_bundle,
        scan_sensitive,
    )
    target = tmp_path / 'diag.json'
    export_bundle(build_bundle(make_trace()), target)
    assert target.exists()
    assert scan_sensitive(target.read_text(encoding='utf-8')) == []


def test_export_refuses_sensitive_bundle(tmp_path):
    from asset_based_agent.technical_platform.diagnostic_bundle import export_bundle
    # 绕过 build_bundle 构造的脏 bundle：导出防线必须独立生效
    dirty = {'schema': 'diagnostic-bundle/v1', 'events': [],
             'notes': '用户密码 password: topsecret'}
    with pytest.raises(ValueError, match='敏感'):
        export_bundle(dirty, tmp_path / 'diag.json')
    assert not (tmp_path / 'diag.json').exists()


def test_bundle_notes_are_redacted():
    from asset_based_agent.technical_platform.diagnostic_bundle import build_bundle
    bundle = build_bundle(make_trace(), notes='password: topsecret 已排除')
    assert 'topsecret' not in str(bundle)
