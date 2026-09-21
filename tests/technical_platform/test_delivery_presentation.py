"""Delivery-presentation contract: one primary deliverable, internal evidence retained."""
import json
import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from asset_based_agent.technical_platform.artifact_contract import (
    EVIDENCE,
    INTERNAL,
    PRIMARY,
    USER,
    artifact_role,
    artifact_visibility,
    detail_display_name,
    display_name_of,
    select_primary,
    stamp_artifact,
    user_artifacts,
)
from asset_based_agent.technical_platform.skills import (
    DETAIL,
    HISTORY,
    WORKFLOW_TO_SKILL,
    digest,
)
from asset_based_agent.technical_platform.store import PlatformStore


def legacy_detail_artifacts():
    return [
        {'name': 'detail_workbook.xlsx', 'path': 'D:/run/output/detail_workbook.xlsx', 'sha256': 'a' * 64},
        {'name': 'completion_status.json', 'path': 'D:/run/output/completion_status.json', 'sha256': 'b' * 64},
        {'name': 'delivery_check_report.json', 'path': 'D:/run/output/delivery_check_report.json', 'sha256': 'c' * 64},
        {'name': 'execution_scope.json', 'path': 'D:/run/output/execution_scope.json', 'sha256': 'd' * 64},
        {'name': 'user_feedback.md', 'path': 'D:/run/output/user_feedback.md', 'sha256': 'e' * 64},
    ]


def legacy_detail_result():
    return {'kind': 'generation', 'ok': True, 'artifacts': legacy_detail_artifacts()}


# --- F01.1 / F02：成功结果只存在一个用户可见主交付物 -------------------------

def test_legacy_detail_result_has_single_user_visible_primary():
    visible = user_artifacts(legacy_detail_result())
    assert [index for index, _ in visible] == [0]
    assert artifact_role(visible[0][1]) == PRIMARY
    assert artifact_visibility(visible[0][1]) == USER


def test_stamped_detail_result_has_single_user_visible_primary():
    artifacts = [stamp_artifact(DETAIL.id, item['name'], item['path'], item['sha256'])
                 for item in legacy_detail_artifacts()]
    visible = user_artifacts({'kind': 'generation', 'ok': True, 'artifacts': artifacts})
    assert len(visible) == 1
    assert visible[0][1]['name'] == 'detail_workbook.xlsx'


# --- F01.2 / F03：内部校验工件保留但标记为内部 --------------------------------

def test_internal_evidence_is_retained_but_marked_internal():
    artifacts = [stamp_artifact(DETAIL.id, item['name'], item['path'], item['sha256'])
                 for item in legacy_detail_artifacts()]
    names = [item['name'] for item in artifacts]
    assert names == ['detail_workbook.xlsx', 'completion_status.json',
                     'delivery_check_report.json', 'execution_scope.json', 'user_feedback.md']
    for item in artifacts[1:]:
        assert artifact_role(item) == EVIDENCE
        assert artifact_visibility(item) == INTERNAL
    for item in legacy_detail_artifacts()[1:]:
        assert artifact_visibility(item) == INTERNAL


def test_staging_workbook_is_never_a_deliverable():
    item = stamp_artifact(DETAIL.id, 'detail_workbook_staging.xlsx', 'D:/run/output/detail_workbook_staging.xlsx', 'f' * 64)
    assert artifact_role(item) == EVIDENCE
    assert artifact_visibility(item) == INTERNAL
    legacy = {'name': 'detail_workbook_staging.xlsx', 'path': 'x', 'sha256': 'f' * 64}
    assert artifact_visibility(legacy) == INTERNAL


def test_skill_declared_json_deliverable_stays_user_visible():
    item = stamp_artifact(WORKFLOW_TO_SKILL.id, 'office_workflow_contract_validation.json',
                          'D:/run/output/office_workflow_contract_validation.json', '0' * 64)
    assert artifact_role(item) == PRIMARY
    assert artifact_visibility(item) == USER
    assert artifact_visibility(
        {'name': 'office_workflow_contract_validation.json', 'path': 'x', 'sha256': '0' * 64}) == USER


def test_unknown_legacy_file_is_not_a_trusted_deliverable():
    item = {'name': 'mystery.xlsx', 'path': 'x', 'sha256': '1' * 64}
    assert artifact_visibility(item) == INTERNAL


def test_invalid_declared_metadata_is_rejected():
    with pytest.raises(ValueError):
        artifact_role({'name': 'detail_workbook.xlsx', 'path': 'x', 'sha256': '1' * 64, 'role': 'boss'})
    with pytest.raises(ValueError):
        artifact_visibility({'name': 'detail_workbook.xlsx', 'path': 'x', 'sha256': '1' * 64,
                             'role': PRIMARY})  # visibility missing
    with pytest.raises(ValueError):
        artifact_visibility({'name': 'detail_workbook.xlsx', 'path': 'x', 'sha256': '1' * 64,
                             'role': PRIMARY, 'visibility': INTERNAL})  # inconsistent
    with pytest.raises(ValueError):
        artifact_visibility({'name': 'detail_workbook.xlsx', 'path': 'x', 'sha256': '1' * 64,
                             'role': EVIDENCE, 'visibility': USER})  # inconsistent
    with pytest.raises(ValueError):
        display_name_of({'name': 'detail_workbook.xlsx', 'path': 'x', 'sha256': '1' * 64,
                         'role': PRIMARY, 'visibility': USER, 'display_name': 'D:/evil/x.xlsx'})


# --- F01.6 / F04：主交付物身份解析 ---------------------------------------------

def test_select_primary_resolves_detail_workbook_legacy_and_stamped():
    legacy = legacy_detail_result()
    index, item = select_primary(legacy, 'detail_workbook.xlsx')
    assert (index, item['name']) == (0, 'detail_workbook.xlsx')
    stamped = {'kind': 'generation', 'ok': True, 'artifacts': [
        stamp_artifact(DETAIL.id, a['name'], a['path'], a['sha256']) for a in legacy_detail_artifacts()]}
    index, item = select_primary(stamped, 'detail_workbook.xlsx')
    assert (index, item['name']) == (0, 'detail_workbook.xlsx')


def test_select_primary_fails_when_missing_or_ambiguous():
    with pytest.raises(ValueError):
        select_primary({'kind': 'generation', 'ok': True, 'artifacts': legacy_detail_artifacts()[1:]},
                       'detail_workbook.xlsx')
    doubled = legacy_detail_result()
    doubled['artifacts'].append(dict(doubled['artifacts'][0]))
    with pytest.raises(ValueError):
        select_primary(doubled, 'detail_workbook.xlsx')


def test_select_primary_rejects_evidence_even_with_expected_name():
    result = {'kind': 'generation', 'ok': True, 'artifacts': [
        {'name': 'detail_workbook.xlsx', 'path': 'x', 'sha256': '1' * 64,
         'role': EVIDENCE, 'visibility': INTERNAL}]}
    with pytest.raises(ValueError):
        select_primary(result, 'detail_workbook.xlsx')


def test_display_name_never_drives_resolution():
    result = {'kind': 'generation', 'ok': True, 'artifacts': [
        stamp_artifact(DETAIL.id, 'detail_workbook.xlsx', 'D:/run/output/detail_workbook.xlsx',
                       'a' * 64, display_name='随便一个名字.xlsx')]}
    index, item = select_primary(result, 'detail_workbook.xlsx')
    assert item['path'] == 'D:/run/output/detail_workbook.xlsx'


# --- F01.3/4/5 / F05：UI 只渲染最终文件 ----------------------------------------

def generation_window(tmp_path, result):
    from PySide6.QtWidgets import QApplication

    from asset_based_agent.technical_platform.app import PlatformWindow
    assert QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('presentation')
    session = store.create_session(project)
    run = store.start_run(session, {'files': []})
    store.transition(run, 'running', 'synthetic')
    store.transition(run, 'validating', 'synthetic')
    store.save_result(run, result)
    store.transition(run, 'succeeded', 'synthetic')
    window = PlatformWindow(store)
    window.reload_projects(project)
    return window, store, session, run


def test_success_chat_shows_only_the_final_workbook(tmp_path):
    window, store, session, run = generation_window(tmp_path, legacy_detail_result())
    try:
        text = window.transcript.toPlainText()
        assert text.count('打开文件') == 1
        for internal in ('completion_status.json', 'delivery_check_report.json',
                         'execution_scope.json', 'user_feedback.md'):
            assert internal not in text
    finally:
        window.close()


def test_success_chat_names_the_final_file(tmp_path):
    window, store, session, run = generation_window(tmp_path, legacy_detail_result())
    try:
        text = window.transcript.toPlainText()
        assert '评估明细表已生成并通过校验' in text
        assert '最终文件' in text
        assert '打开所在文件夹' in text
    finally:
        window.close()


def test_primary_link_still_opens_with_run_session_authorization(tmp_path):
    result = legacy_detail_result()
    window, store, session, run = generation_window(tmp_path, result)
    try:
        output = tmp_path / 'runs' / run / 'output'
        output.mkdir(parents=True)
        workbook = output / 'detail_workbook.xlsx'
        workbook.write_bytes(b'synthetic workbook')
        result['artifacts'][0].update(path=str(workbook), sha256=digest(workbook))
        store.save_result(run, result)
        from asset_based_agent.technical_platform.generation import artifact_path
        assert artifact_path(store, session, run, 0) == workbook.resolve()
        other = store.create_session(store.session(session)['project'])
        with pytest.raises(PermissionError):
            artifact_path(store, other, run, 0)
    finally:
        window.close()


# --- F06：显示名 ---------------------------------------------------------------

def cover_report(work, writes, status='pass'):
    output = work / 'output'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'cover_fill_report.json').write_text(json.dumps(
        {'status': status, 'writes': writes}, ensure_ascii=False), encoding='utf-8')


def test_display_name_uses_validated_subject_and_date(tmp_path):
    cover_report(tmp_path, {'F7': '北京绵脉科技有限公司', 'F9': 2026, 'H9': 6, 'J9': 30})
    assert detail_display_name(tmp_path) == '北京绵脉科技有限公司评估明细表（2026-06-30）.xlsx'


def test_display_name_sanitizes_illegal_characters(tmp_path):
    cover_report(tmp_path, {'F7': '甲<方>:/"\\|?*\n公司', 'F9': 2026, 'H9': 6, 'J9': 30})
    name = detail_display_name(tmp_path)
    assert name.endswith('评估明细表（2026-06-30）.xlsx')
    for char in '<>:"/\\|?*\n':
        assert char not in name


def test_display_name_truncates_overlong_subject(tmp_path):
    cover_report(tmp_path, {'F7': '长' * 200, 'F9': 2026, 'H9': 6, 'J9': 30})
    assert len(detail_display_name(tmp_path)) <= 120


@pytest.mark.parametrize('writes', [
    {'F7': '北京绵脉科技有限公司'},                                  # 缺日期
    {'F9': 2026, 'H9': 6, 'J9': 30},                                # 缺主体
    {'F7': '   ', 'F9': 2026, 'H9': 6, 'J9': 30},                   # 空主体
    {'F7': '北京绵脉科技有限公司', 'F9': 2026, 'H9': 13, 'J9': 30},  # 非法日期
    {'F7': '北京绵脉科技有限公司', 'F9': True, 'H9': 6, 'J9': 30},   # 类型错误
])
def test_display_name_falls_back_safely(tmp_path, writes):
    cover_report(tmp_path, writes)
    assert detail_display_name(tmp_path) == '最终评估明细表.xlsx'


def test_display_name_falls_back_without_passed_cover_gate(tmp_path):
    cover_report(tmp_path, {'F7': '北京绵脉科技有限公司', 'F9': 2026, 'H9': 6, 'J9': 30}, status='fail')
    assert detail_display_name(tmp_path) == '最终评估明细表.xlsx'
    assert detail_display_name(tmp_path / 'missing') == '最终评估明细表.xlsx'


def test_history_primary_display_name(tmp_path):
    item = stamp_artifact(HISTORY.id, 'history_fragment.docx', 'D:/run/output/history_fragment.docx', '2' * 64)
    assert artifact_role(item) == PRIMARY
    assert artifact_visibility(item) == USER


def test_legacy_detail_display_name_derived_beside_stored_path(tmp_path):
    work = tmp_path / 'run'
    cover_report(work, {'F7': '北京绵脉科技有限公司', 'F9': 2026, 'H9': 6, 'J9': 30})
    item = {'name': 'detail_workbook.xlsx', 'path': str(work / 'output' / 'detail_workbook.xlsx'),
            'sha256': 'a' * 64}
    assert display_name_of(item) == '北京绵脉科技有限公司评估明细表（2026-06-30）.xlsx'
    orphan = {'name': 'detail_workbook.xlsx', 'path': str(tmp_path / 'gone' / 'output' / 'detail_workbook.xlsx'),
              'sha256': 'a' * 64}
    assert display_name_of(orphan) == '最终评估明细表.xlsx'
