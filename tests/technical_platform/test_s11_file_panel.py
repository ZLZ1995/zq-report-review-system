"""S11 文件面板重构（先红后绿）。

验收（任务书 S11）：文件角色、期间识别、本轮使用状态、处理状态、
文件搜索、文件过滤、批量选择、隐藏 hash、文件详情。
铁律：勾选/选择契约不变（UserRole=file id + checkState）；
列表默认不显示 hash；派生信息全部来自真实文件记录与任务快照。
"""
from __future__ import annotations

import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.file_panel import (
    build_file_rows,
    classify_file_role,
    detect_period,
    file_detail_text,
    filter_rows,
    format_size,
    row_label,
)

# ------------------------------------------------------------ 文件角色

def test_classify_file_role():
    assert classify_file_role('2024年度审核报告.docx') == '报告'
    assert classify_file_role('往来明细表.xlsx') == '明细'
    assert classify_file_role('凭证扫描件.pdf') == '凭证'
    assert classify_file_role('采购合同.docx') == '合同'
    assert classify_file_role('导出数据.json') == '数据'
    assert classify_file_role('随手记录.zip') == '资料'


# ------------------------------------------------------------ 期间识别

def test_detect_period():
    assert detect_period('A8T-BS202607.xlsx') == '2026-07'
    assert detect_period('2024年度报告.docx') == '2024年度'
    assert detect_period('2023Q2明细.xlsx') == '2023Q2'
    assert detect_period('无期间文件.docx') is None


# ------------------------------------------------------------ 行视图

def _rows():
    files = [
        {'id': 'f1', 'name': '2024年度审核报告.docx', 'size': 2048,
         'sha256': 'a' * 64, 'created': '2026-09-01 10:00'},
        {'id': 'f2', 'name': '往来明细202607.xlsx', 'size': 1536,
         'sha256': 'b' * 64, 'created': '2026-09-02 10:00'},
        {'id': 'f3', 'name': '其它.zip', 'size': 512,
         'sha256': 'c' * 64, 'created': '2026-09-03 10:00'},
    ]
    return build_file_rows(files, selected_ids={'f1'},
                           used_ids={'f1', 'f2'})


def test_build_file_rows_derives_role_period_usage():
    rows = _rows()
    assert rows[0].role == '报告' and rows[0].period == '2024年度'
    assert rows[0].selected is True and rows[0].used_in_tasks is True
    assert rows[1].role == '明细' and rows[1].period == '2026-07'
    assert rows[1].selected is False and rows[1].used_in_tasks is True
    assert rows[2].used_in_tasks is False


def test_row_label_hides_hash_and_shows_meta():
    rows = _rows()
    label = row_label(rows[0], files_map={'f1': 'a' * 64})
    assert label.splitlines()[0] == '2024年度审核报告.docx'
    assert 'aaaa' not in label, '列表不得显示 hash'
    assert '报告' in label and '2024年度' in label
    assert 'KB' in label or 'B' in label
    assert '本轮已选' in label
    label3 = row_label(rows[2], files_map={})
    assert '未使用' in label3


def test_format_size():
    assert format_size(512) == '512 B'
    assert format_size(2048) == '2.0 KB'
    assert format_size(3 * 1024 * 1024) == '3.0 MB'


def test_filter_rows_query_and_kind():
    rows = _rows()
    assert [r.file_id for r in filter_rows(rows, '明细', 'all')] == ['f2']
    assert [r.file_id for r in filter_rows(rows, '', 'selected')] == ['f1']
    assert [r.file_id for r in filter_rows(rows, '', 'unused')] == ['f3']
    assert [r.file_id for r in filter_rows(rows, '', 'used')] == ['f1', 'f2']
    assert filter_rows(rows, '不存在', 'all') == []


def test_file_detail_text_contains_full_info_including_hash():
    rows = _rows()
    detail = file_detail_text(rows[0], sha256='a' * 64, path='/data/report.docx')
    assert '2024年度审核报告.docx' in detail
    assert 'a' * 64 in detail, '详情可以展示完整 hash'
    assert '报告' in detail and '2024年度' in detail


# ------------------------------------------------------------ Qt 集成

def _make_window(tmp_path):
    from asset_based_agent.technical_platform.app import PlatformWindow
    from asset_based_agent.technical_platform.store import PlatformStore
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'ui.sqlite', 'tester')
    project = store.create_project('s11 项目')
    store.create_session(project, 's11 会话')
    window = PlatformWindow(store)
    window.reload_projects(project)
    return app, store, window, project


def _add_file(store, project, tmp_path, name, data=b'x'):
    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / name
    path.write_bytes(data)
    return store.add_file(project, path, digest(path))


def test_file_panel_shows_meta_hides_hash_keeps_selection_contract(tmp_path):
    app, store, window, project = _make_window(tmp_path)
    f1 = _add_file(store, project, tmp_path, '2024年度审核报告.docx')
    _add_file(store, project, tmp_path, '往来明细202607.xlsx')
    window.refresh_details(selected_ids={f1})
    app.processEvents()

    texts = [window.files.item(i).text() for i in range(window.files.count())]
    assert texts[0].splitlines()[0] == '2024年度审核报告.docx'
    assert '报告' in texts[0] and '本轮已选' in texts[0]
    assert '明细' in texts[1] and '2026-07' in texts[1]
    for i in range(window.files.count()):
        item = window.files.item(i)
        assert len(item.text()) < 200
        assert not any(c * 20 in item.text() for c in 'abcdef'), \
            '列表不得显示 hash 前缀'
    # 选择契约不变
    assert window.selected_file_ids() == {f1}
    assert window.files.item(0).data(Qt.ItemDataRole.UserRole) == f1
    window.close()


def test_file_search_filter_and_batch_selection(tmp_path):
    app, store, window, project = _make_window(tmp_path)
    f1 = _add_file(store, project, tmp_path, '2024年度审核报告.docx')
    f2 = _add_file(store, project, tmp_path, '往来明细202607.xlsx')
    f3 = _add_file(store, project, tmp_path, '其它.zip')
    # 真实使用证据：历史任务快照的 selected_files
    session_id = store.sessions(project)[0]['id']
    store.start_run(session_id, {'selected_files': [
        {'id': f1, 'sha256': 'a' * 64, 'version': 'a' * 64},
        {'id': f2, 'sha256': 'b' * 64, 'version': 'b' * 64},
    ]})
    window.refresh_details(selected_ids={f1})
    app.processEvents()

    # 搜索：隐藏不匹配行但保留其勾选状态
    window.file_search.setText('明细')
    app.processEvents()
    assert window.files.item(0).isHidden()
    assert not window.files.item(1).isHidden()
    assert window.selected_file_ids() == {f1}, '搜索隐藏不得丢勾选'

    # 过滤：未使用
    window.file_search.setText('')
    window.file_filter.setCurrentIndex(
        window.file_filter.findText('未使用'))
    app.processEvents()
    visible = [window.files.item(i) for i in range(window.files.count())
               if not window.files.item(i).isHidden()]
    assert [v.data(Qt.ItemDataRole.UserRole) for v in visible] == [f3]

    # 批量选择只作用于可见行
    window.file_filter.setCurrentIndex(window.file_filter.findText('全部文件'))
    window.file_search.setText('2')
    app.processEvents()
    window.select_visible_files()
    app.processEvents()
    assert window.selected_file_ids() == {f1, f2}, \
        '批量选择只勾选可见行，已选保留'
    window.clear_visible_files()
    app.processEvents()
    assert f2 not in window.selected_file_ids()
    window.close()


def test_file_detail_panel_on_double_click(tmp_path):
    app, store, window, project = _make_window(tmp_path)
    _add_file(store, project, tmp_path, '2024年度审核报告.docx')
    window.refresh_details()
    app.processEvents()
    item = window.files.item(0)
    window.show_file_detail(item)
    detail = window.file_detail.text()
    assert '2024年度审核报告.docx' in detail
    assert '报告' in detail and '2024年度' in detail
    assert store.files(project)[0]['sha256'][:16] in detail, \
        '详情显示完整 hash'
    window.close()
