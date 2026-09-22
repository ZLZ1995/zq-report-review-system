"""S08：业务 Run Harness 包装为 Agent Tool 的合同测试。

七个工具（inspect/analyze/execute/query/cancel/list/annotate）驱动与现有
UI 完全相同的 build_task_spec → start_run → execute_task 链路，保留全部硬
门禁；输出只允许有界摘要与最终成果引用，绝不泄露内部状态文件、临时目录、
原始堆栈或全量日志。
"""
import asyncio
import json
import threading
from hashlib import sha256
from pathlib import Path

import pytest

from asset_based_agent.technical_platform.agent_core.cancellation import CancelToken
from asset_based_agent.technical_platform.agent_core.contracts import ModelEvent
from asset_based_agent.technical_platform.agent_core.errors import (
    ToolFailed,
    ToolInvalidArguments,
    ToolPermissionDenied,
)
from asset_based_agent.technical_platform.agent_core.fakes import (
    FakeModelPort,
    InMemorySessionRepo,
)
from asset_based_agent.technical_platform.agent_core.runtime import AgentKernel
from asset_based_agent.technical_platform.business_tools import business_tools
from asset_based_agent.technical_platform.business_tools.service import (
    BusinessRunService,
)
from asset_based_agent.technical_platform.skills import (
    HISTORY,
    PREFLIGHT,
    digest,
)
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import build_task_spec


def run(coro):
    return asyncio.run(coro)


def make_store(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    project = store.create_project('one')
    session = store.create_session(project)
    return store, project, session


def add_file(store, project, tmp_path, name='资料.xlsx'):
    from openpyxl import Workbook

    path = tmp_path / name
    wb = Workbook()
    wb.active['A1'] = '合成表头'
    wb.save(path)
    wb.close()
    return store.add_file(project, path, digest(path))


def add_docx(store, project, tmp_path, paragraph, name='评估报告.docx'):
    from docx import Document

    path = tmp_path / name
    doc = Document()
    doc.add_paragraph(paragraph)
    doc.save(path)
    return store.add_file(project, path, digest(path))


def make_service(store, session):
    return BusinessRunService(store, session)


def tool_map(service):
    return {t.descriptor.name: t for t in business_tools(service)}


def preflight_args(file_id, **overrides):
    args = {
        'skill_id': PREFLIGHT.id,
        'skill_version': PREFLIGHT.version,
        'skill_hash': sha256(b'').hexdigest(),
        'target_file_ids': [file_id],
        'reference_file_ids': [],
        'user_goal': '预检这份资料',
        'confirmed_facts': [],
        'permission_receipt': {'granted': ['read_selected_files']},
        'idempotency_key': 'idem-1',
    }
    args.update(overrides)
    return args


def make_succeeded_review_run(store, session, file_id, paragraph):
    project = store.session(session)['project']
    files = [f for f in store.files(project) if f['id'] == file_id]
    spec = build_task_spec(store, session, '审核这份文件', PREFLIGHT, files)
    run_id = store.start_run(session, spec.to_snapshot())
    store.claim_run(run_id)
    store.save_result(run_id, {
        'kind': 'review', 'model_called': True, 'files': [],
        'issues': [{'original_text': paragraph, 'description': '表述待核实',
                    'recommendation': '请复核', 'source_file_id': file_id,
                    'requires_verification': True}]})
    store.transition(run_id, 'validating', '校验')
    store.transition(run_id, 'succeeded', '完成')
    return run_id


# ------------------------------------------------------------- descriptors

def test_seven_tools_with_declared_risks(tmp_path):
    store, _project, session = make_store(tmp_path)
    tools = tool_map(make_service(store, session))
    assert set(tools) == {
        'inspect_project_files', 'analyze_file_roles', 'execute_skill_plan',
        'query_business_run', 'cancel_business_run', 'list_final_artifacts',
        'annotate_reviewed_files', 'read_project_file'}
    assert tools['inspect_project_files'].descriptor.risk == 'local_readonly'
    assert tools['analyze_file_roles'].descriptor.risk == 'local_readonly'
    assert tools['query_business_run'].descriptor.risk == 'local_readonly'
    assert tools['list_final_artifacts'].descriptor.risk == 'local_readonly'
    assert tools['execute_skill_plan'].descriptor.risk == 'network_write'
    assert tools['cancel_business_run'].descriptor.risk == 'process'
    assert tools['annotate_reviewed_files'].descriptor.risk == 'copy_modify'
    for tool in tools.values():
        assert tool.descriptor.description.strip()


# ------------------------------------------------------------ inspection

def test_inspect_project_files_returns_metadata_without_paths(tmp_path):
    store, project, session = make_store(tmp_path)
    first = add_file(store, project, tmp_path, 'a.xlsx')
    second = add_file(store, project, tmp_path, 'b.xlsx')
    service = make_service(store, session)
    result = run(tool_map(service)['inspect_project_files'].execute(None, {}, CancelToken()))
    assert result.status == 'succeeded'
    rows = {item['id']: item for item in result.result['files']}
    assert set(rows) == {first, second}
    for item in rows.values():
        assert item['name'].endswith('.xlsx')
        assert len(item['sha256']) == 64 and item['size'] > 0
        assert 'path' not in item
    assert str(tmp_path) not in json.dumps(result.result, ensure_ascii=False)


def test_analyze_file_roles_classifies_known_patterns(tmp_path):
    store, project, session = make_store(tmp_path)
    workbook = add_file(store, project, tmp_path, '测算明细表.xlsx')
    report = add_docx(store, project, tmp_path, '正文', name='资产评估报告.docx')
    service = make_service(store, session)
    result = run(tool_map(service)['analyze_file_roles'].execute(
        None, {'file_ids': [workbook, report]}, CancelToken()))
    assert result.status == 'succeeded'
    roles = {item['id']: item['role'] for item in result.result['files']}
    assert roles[workbook] == 'calculation_workbook'
    assert roles[report] == 'main_report'
    with pytest.raises(ToolInvalidArguments):
        make_service(store, session).analyze_roles(['不属于项目的id'])


# --------------------------------------------------------------- execute

def test_execute_preflight_succeeds_with_bounded_output(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    result = run(tool_map(service)['execute_skill_plan'].execute(
        None, preflight_args(file_id), CancelToken()))
    assert result.status == 'succeeded'
    payload = result.result
    assert payload['state'] == 'succeeded' and payload['validation_status'] == 'passed'
    assert payload['run_id'] and len(payload['summary']) <= 2000
    assert payload['artifacts'] == []
    assert isinstance(payload['warnings'], list)
    assert 'query_business_run' in payload['follow_up_capabilities']
    # 输出合同：无内部状态文件、无临时目录、无堆栈
    blob = json.dumps(payload, ensure_ascii=False) + result.content
    for forbidden in ('completion_status', 'delivery_check_report', 'execution_scope',
                      'material_analysis', 'Traceback', str(tmp_path)):
        assert forbidden not in blob
    assert store.run(payload['run_id'])['state'] == 'succeeded'
    assert service.active_runs() == {}


def test_execute_replays_same_run_for_repeated_idempotency_key(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    first = service.execute_skill_plan(**preflight_args(file_id))
    second = service.execute_skill_plan(**preflight_args(file_id))
    assert first['run_id'] == second['run_id']
    assert len(store.runs(session)) == 1


def test_execute_denies_missing_permission_grant(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    with pytest.raises(ToolPermissionDenied):
        service.execute_skill_plan(**preflight_args(file_id, permission_receipt={'granted': []}))
    assert store.runs(session) == []


def test_execute_denies_generation_without_generate_grant(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    with pytest.raises(ToolPermissionDenied):
        service.execute_skill_plan(**preflight_args(
            file_id, skill_id=HISTORY.id, skill_version=HISTORY.version,
            skill_hash='0' * 64, input_roles={'source_excel': file_id}))
    assert store.runs(session) == []


def test_execute_rejects_version_and_hash_mismatch(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    with pytest.raises(ToolPermissionDenied):
        service.execute_skill_plan(**preflight_args(file_id, skill_version='9.9.9'))
    from asset_based_agent.technical_platform.generation import bundle_fingerprint
    wrong = sha256(b'forged').hexdigest()
    with pytest.raises(ToolPermissionDenied):
        service.execute_skill_plan(**preflight_args(
            file_id, skill_id=HISTORY.id, skill_version=HISTORY.version,
            skill_hash=wrong, input_roles={'source_excel': file_id},
            permission_receipt={'granted': ['read_selected_files', 'generate_artifacts']}))
    assert sha256(bundle_fingerprint(HISTORY.id).encode('utf-8')).hexdigest() != wrong
    assert store.runs(session) == []


def test_execute_failure_is_locatable_and_preserves_session(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    run_id = service.queue_skill_plan(**preflight_args(file_id))
    # 执行前篡改已登记附件：版本校验必须失败且 run 转 failed
    row = next(f for f in store.files(project) if f['id'] == file_id)
    Path(row['path']).write_bytes(b'corrupted-by-outsider')
    with pytest.raises(ToolFailed) as captured:
        service.drive_run(run_id, threading.Event())
    message = str(captured.value)
    assert run_id[:8] in message and 'Traceback' not in message
    assert store.run(run_id)['state'] == 'failed'
    # 失败后工具层返回 failed ToolResult 而不是抛出堆栈
    result = run(tool_map(service)['execute_skill_plan'].execute(
        None, preflight_args(file_id, idempotency_key='idem-2'), CancelToken()))
    assert result.status == 'failed' and result.error_code == 'tool.failed'


def test_execute_requires_registered_skill_and_known_files(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    with pytest.raises(ToolInvalidArguments):
        service.execute_skill_plan(**preflight_args(file_id, skill_id='不存在.skill'))
    with pytest.raises(ToolInvalidArguments):
        service.execute_skill_plan(**preflight_args('别的文件id'))


# ------------------------------------------------------- query and cancel

def test_query_business_run_reports_state(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    payload = service.execute_skill_plan(**preflight_args(file_id))
    found = service.query_run(payload['run_id'])
    assert found['run_id'] == payload['run_id'] and found['state'] == 'succeeded'
    with pytest.raises(ToolFailed):
        service.query_run('不存在的run')


def test_cancel_queued_business_run(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    run_id = service.queue_skill_plan(**preflight_args(file_id))
    outcome = service.cancel_run(run_id)
    assert outcome['state'] == 'cancelled'
    assert store.run(run_id)['state'] == 'cancelled'
    with pytest.raises(ToolFailed):
        service.cancel_run(run_id)


# ------------------------------------------------------------ artifacts

def test_list_final_artifacts_filters_internal_files(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    run_id = service.queue_skill_plan(**preflight_args(file_id))
    store.claim_run(run_id)
    store.save_result(run_id, {'kind': 'generation', 'artifacts': [
        {'name': 'completion_status.json', 'path': str(tmp_path / 'a.json'),
         'sha256': 'a' * 64, 'role': 'evidence', 'visibility': 'internal'},
        {'name': 'user_feedback.md', 'path': str(tmp_path / 'b.md'),
         'sha256': 'b' * 64, 'role': 'evidence', 'visibility': 'internal'},
        {'name': 'financial_brief.docx', 'path': str(tmp_path / 'c.docx'),
         'sha256': 'c' * 64, 'role': 'primary', 'visibility': 'user',
         'display_name': '财务状况简表.docx'},
    ]})
    store.transition(run_id, 'validating', '校验')
    store.transition(run_id, 'succeeded', '完成')
    listed = run(tool_map(service)['list_final_artifacts'].execute(
        None, {'run_id': run_id}, CancelToken()))
    assert listed.status == 'succeeded'
    assert [a['name'] for a in listed.result['artifacts']] == ['financial_brief.docx']
    artifact = listed.result['artifacts'][0]
    assert artifact['display_name'] == '财务状况简表.docx' and artifact['index'] == 2
    assert 'path' not in artifact
    assert str(tmp_path) not in json.dumps(listed.result, ensure_ascii=False)


# ------------------------------------------------------------ annotate

def test_annotate_reviewed_files_end_to_end_keeps_original_hash(tmp_path):
    paragraph = '本次评估结论以公开市场数据为依据。'
    store, project, session = make_store(tmp_path)
    file_id = add_docx(store, project, tmp_path, paragraph)
    service = make_service(store, session)
    run_id = make_succeeded_review_run(store, session, file_id, paragraph)
    row = next(f for f in store.files(project) if f['id'] == file_id)
    before = digest(Path(row['path']))
    outbox = tmp_path / 'out'
    outbox.mkdir()
    result = run(tool_map(service)['annotate_reviewed_files'].execute(
        None, {'run_id': run_id, 'selected': [1], 'directory': str(outbox)},
        CancelToken()))
    assert result.status == 'succeeded'
    payload = result.result
    assert len(payload['artifacts']) == 1
    copy_name = payload['artifacts'][0]['name']
    assert '_标注版_' in copy_name and copy_name.endswith('.docx')
    assert 'path' not in payload['artifacts'][0]
    produced = list(outbox.glob('*_标注版_*.docx'))
    assert len(produced) == 1
    assert digest(Path(row['path'])) == before
    stored = json.loads(store.run(run_id)['result'])
    assert stored['annotations'][-1]['files']


def test_annotate_rejects_runs_without_review_issues(tmp_path):
    store, project, session = make_store(tmp_path)
    file_id = add_file(store, project, tmp_path)
    service = make_service(store, session)
    payload = service.execute_skill_plan(**preflight_args(file_id))
    with pytest.raises(ToolFailed):
        service.annotate(payload['run_id'], [1], str(tmp_path))


# ---------------------------------------------------- kernel integration

def test_failed_business_tool_does_not_break_agent_session(tmp_path):
    store, project, session = make_store(tmp_path)
    add_file(store, project, tmp_path)
    service = make_service(store, session)
    repo = InMemorySessionRepo()
    repo.create_session('s1', project_id='p1', owner_id='alice', title='会话')
    scripts = [
        [ModelEvent('message_start', {}),
         ModelEvent('tool_call_complete',
                    {'id': 'c1', 'name': 'execute_skill_plan',
                     'arguments': {'skill_id': PREFLIGHT.id}}),
         ModelEvent('message_complete', {})],
        [ModelEvent('message_start', {}),
         ModelEvent('text_delta', {'text': '工具参数不完整，已放弃执行'}),
         ModelEvent('message_complete', {})],
        [ModelEvent('message_start', {}),
         ModelEvent('text_delta', {'text': '第二句回复'}),
         ModelEvent('message_complete', {})],
    ]
    kernel = AgentKernel(repo=repo, model=FakeModelPort(scripts),
                         tools=business_tools(service))
    first = run(kernel.submit('s1', 'main', {'text': '帮我审核'}))
    assert repo.get_operation(first.operation_id).status == 'completed'
    calls = repo.tool_calls(first.operation_id)
    assert len(calls) == 1 and calls[0].status == 'failed'
    second = run(kernel.submit('s1', 'main', {'text': '继续说'}))
    assert repo.get_operation(second.operation_id).status == 'completed'
    assert repo.open_operations() == []
