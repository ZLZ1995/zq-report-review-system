"""S12 成果交付与任务历史（先红后绿）。

验收（任务书 S12）：ArtifactCard、成果 Tab、任务 Tab、历史成果可访问、
打开/另存为、生成说明、任务 ID / operation ID 详情。
铁律：成果/任务数据全部来自 store 真实 runs 记录；unknown 状态显示
"状态待核对"绝不显示"失败"；另存为走 staging + atomic rename。
"""
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.artifact_panel import (
    artifact_detail_text,
    artifact_row_text,
    collect_artifacts,
    state_label,
    task_detail_text,
    task_row_text,
)

# ------------------------------------------------------------ 夹具辅助

def _store(tmp_path):
    from asset_based_agent.technical_platform.store import PlatformStore
    store = PlatformStore(tmp_path / 'ui.sqlite', 'tester')
    project = store.create_project('s12 项目')
    store.create_session(project, 's12 会话')
    return store, project


def _run(store, project, result=None, snapshot=None):
    """走真实状态机路径创建 succeeded run。"""
    session_id = store.sessions(project)[0]['id']
    run_id = store.start_run(session_id, snapshot or {'user_request': '生成'})
    store.transition(run_id, 'running', 't')
    store.transition(run_id, 'validating', 't')
    if result is not None:
        store.save_result(run_id, result)
    store.transition(run_id, 'succeeded', 't')
    return run_id


def _generation_result(tmp_path, run_id, store):
    """真实磁盘成果 + generation result。"""
    out = store.path.parent / 'runs' / run_id / 'output'
    out.mkdir(parents=True)
    target = out / 'final.docx'
    target.write_bytes(b'deliverable')
    from asset_based_agent.technical_platform.skills import digest
    return {
        'kind': 'generation', 'ok': True,
        'artifacts': [
            {'name': 'final.docx', 'path': str(target),
             'sha256': digest(target),
             'role': 'primary', 'visibility': 'user',
             'display_name': '评估报告.docx'},
            {'name': 'validation.json', 'path': str(out / 'validation.json'),
             'sha256': 'x', 'role': 'validation_evidence',
             'visibility': 'internal'},
        ],
    }


# ------------------------------------------------------------ 纯逻辑

def test_state_label_known_and_unknown():
    assert state_label('succeeded') == '已成功'
    assert state_label('running') == '运行中'
    assert state_label('mystery') == '状态待核对', '未知状态绝不显示失败'
    assert state_label('') == '状态待核对'


def test_collect_artifacts_empty_project(tmp_path):
    store, project = _store(tmp_path)
    assert collect_artifacts(store, project) == []


def test_collect_generation_user_artifacts_only(tmp_path):
    store, project = _store(tmp_path)
    run_id = _run(store, project)
    store.save_result(run_id, _generation_result(tmp_path, run_id, store))
    entries = collect_artifacts(store, project)
    assert len(entries) == 1, '内部证据文件不得出现在成果列表'
    entry = entries[0]
    assert entry.name == '评估报告.docx'
    assert entry.kind == 'generation'
    assert entry.state == 'succeeded'
    assert entry.run_id == run_id
    assert entry.session_id == store.sessions(project)[0]['id']
    assert entry.path.endswith('final.docx')


def test_collect_review_exported_report(tmp_path):
    store, project = _store(tmp_path)
    report = tmp_path / 'report.docx'
    report.write_bytes(b'r')
    _run(store, project, result={
        'kind': 'review', 'issues': ['x'],
        'exported_report': str(report),
        'annotations': [{'files': [str(tmp_path / 'ann.docx')]}],
    })
    entries = collect_artifacts(store, project)
    kinds = {e.kind for e in entries}
    assert 'review' in kinds and 'review_annotation' in kinds
    assert any(e.path == str(report) for e in entries)


def test_collect_skips_corrupt_result(tmp_path):
    store, project = _store(tmp_path)
    run_id = _run(store, project)
    with store.connect() as db:
        db.execute("UPDATE runs SET result='not-json' WHERE id=?", (run_id,))
    assert collect_artifacts(store, project) == [], '损坏结果必须跳过而非崩溃'


def test_artifact_row_and_detail_text(tmp_path):
    store, project = _store(tmp_path)
    run_id = _run(store, project)
    store.save_result(run_id, _generation_result(tmp_path, run_id, store))
    entry = collect_artifacts(store, project)[0]
    row = artifact_row_text(entry)
    assert row.splitlines()[0] == '评估报告.docx'
    assert run_id[:9] in row and '已成功' in row
    detail = artifact_detail_text(entry)
    assert run_id in detail and entry.path in detail


def test_task_row_and_detail_text(tmp_path):
    store, project = _store(tmp_path)
    snapshot = {'user_request': '生成明细表', 'operation_id': 'op-123'}
    run_id = _run(store, project, snapshot=snapshot)
    run = store.run(run_id)
    row = task_row_text(run, snapshot)
    assert run_id[:9] in row and '已成功' in row
    detail = task_detail_text(run, snapshot)
    assert run_id in detail, '任务详情必须含完整任务 ID'
    assert 'op-123' in detail, '任务详情必须含 operation ID'
    assert run['session'] in detail


# ------------------------------------------------------------ Qt 集成

def _make_window(tmp_path):
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'ui.sqlite', 'tester')
    project = store.create_project('s12 项目')
    store.create_session(project, 's12 会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    return app, store, window, project


def test_artifacts_and_tasks_tabs_populated(tmp_path):
    app, store, window, project = _make_window(tmp_path)
    run_id = _run(store, project, snapshot={'user_request': '生成'})
    store.save_result(run_id, _generation_result(tmp_path, run_id, store))
    window.refresh_details()
    app.processEvents()
    tab_titles = [window.details.tabText(i) for i in range(window.details.count())]
    assert '成果' in tab_titles and '任务' in tab_titles
    assert window.artifacts_list.count() == 1
    assert window.tasks_list.count() == 1
    text = window.artifacts_list.item(0).text()
    assert '评估报告.docx' in text and run_id[:9] in text
    window.close()


def test_task_detail_on_double_click(tmp_path):
    app, store, window, project = _make_window(tmp_path)
    run_id = _run(store, project, snapshot={'user_request': '生成', 'operation_id': 'op-9'})
    window.refresh_details()
    app.processEvents()
    window.show_task_detail(window.tasks_list.item(0))
    detail = window.task_detail.text()
    assert run_id in detail and 'op-9' in detail
    window.close()


def test_open_and_save_artifact_as(tmp_path, monkeypatch):
    app, store, window, project = _make_window(tmp_path)
    run_id = _run(store, project)
    store.save_result(run_id, _generation_result(tmp_path, run_id, store))
    window.refresh_details()
    app.processEvents()

    opened = []
    monkeypatch.setattr(
        'asset_based_agent.technical_platform.app.QDesktopServices.openUrl',
        lambda url: opened.append(url) or True)
    window.open_selected_artifact()
    assert opened, '打开成果必须走系统默认应用'

    target = tmp_path / 'copy.docx'
    monkeypatch.setattr(
        'asset_based_agent.technical_platform.app.QFileDialog.getSaveFileName',
        lambda *a, **k: (str(target), ''))
    window.save_artifact_as()
    assert target.read_bytes() == b'deliverable', '另存为内容必须与原件一致'
    assert not list(tmp_path.glob('*.part')), 'staging 临时文件不得残留'
    window.close()
