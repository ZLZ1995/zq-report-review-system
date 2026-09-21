import pytest
from docx import Document

from asset_based_agent.technical_platform.store import PlatformStore


def case(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'tester')
    project = store.create_project('Review project')
    session = store.create_session(project)
    run = store.start_run(session, {'files': []})
    store.transition(run, 'running', '')
    store.transition(run, 'validating', '')
    store.save_result(run, {'kind': 'review', 'files': [], 'issues': [{
        'source_file_id': 'f', 'source_file_name': 'report.docx',
        'category': 'data_inconsistency', 'risk_level': 'low',
        'location': {'paragraph': 4}, 'description': 'Evidence mismatch',
        'recommendation': 'Check source', 'confidence': 0.8,
    }]})
    store.transition(run, 'succeeded', '')
    return store, run


def test_export_saved_review_as_standard_word(tmp_path):
    from asset_based_agent.technical_platform.report_export import export_review
    store, run = case(tmp_path)
    path = export_review(store, run, tmp_path / 'chosen.docx')
    text = '\n'.join(p.text for p in Document(path).paragraphs)
    assert '资产评估报告审核记录' in text
    assert 'Evidence mismatch' in text
    assert '尚未确认修改' in text
    assert '已忽略问题汇总' in text


def test_preflight_is_not_exportable_as_review(tmp_path):
    from asset_based_agent.technical_platform.report_export import export_review
    store, run = case(tmp_path)
    store.save_result(run, {'kind': 'preflight'})
    with pytest.raises(ValueError):
        export_review(store, run, tmp_path / 'no.docx')
    assert not (tmp_path / 'no.docx').exists()


def test_export_never_overwrites_source(tmp_path):
    import json

    from asset_based_agent.technical_platform.report_export import export_review
    store, run = case(tmp_path)
    source = tmp_path / 'source.docx'
    source.write_bytes(b'original')
    with store.connect() as db:
        db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps({'files': [{'path': str(source)}]}), run))
    with pytest.raises(ValueError, match='原文件'):
        export_review(store, run, source)
    assert source.read_bytes() == b'original'


def test_chat_export_link_and_file_link(tmp_path, monkeypatch):
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QFileDialog

    from asset_based_agent.technical_platform.app import PlatformWindow
    app = QApplication.instance() or QApplication([])
    store, run = case(tmp_path)
    window = PlatformWindow(store)
    project = store.session(store.run(run)['session'])['project']
    window.reload_projects(project)
    assert '生成标准Word审核报告' in window.transcript.toPlainText()
    target = tmp_path / 'selected.docx'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a, **kw: (str(target), ''))
    window.handle_report_link(QUrl(f'zq-export:{run}'))
    assert target.is_file()
    assert '打开文件' in window.transcript.toPlainText()
    window.close()
    assert app is not None


def test_existing_unrelated_document_is_preserved(tmp_path):
    from asset_based_agent.technical_platform.report_export import export_review
    store, run = case(tmp_path)
    target = tmp_path / 'existing.docx'
    target.write_bytes(b'keep')
    with pytest.raises(ValueError, match='新文件名'):
        export_review(store, run, target)
    assert target.read_bytes() == b'keep'
