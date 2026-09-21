import json
from pathlib import Path

import pytest
from docx import Document
from test_export import case

from asset_based_agent.technical_platform.session_service import SessionService
from asset_based_agent.technical_platform.skills import digest


@pytest.mark.parametrize('kind', ['report', 'annotation'])
def test_review_delivery_version_recorded_and_branch_detects_replacement(tmp_path, kind):
    from asset_based_agent.technical_platform.annotations import generate_annotations
    from asset_based_agent.technical_platform.report_export import export_review
    store, run = case(tmp_path)
    session = store.run(run)['session']
    if kind == 'report':
        path = export_review(store, run, tmp_path / 'report.docx')
    else:
        source = tmp_path / 'source.docx'
        document = Document()
        document.add_paragraph('synthetic content')
        document.save(source)
        project = store.session(session)['project']
        file_id = store.add_file(project, source, digest(source))
        files = store.files(project)
        result = json.loads(store.run(run)['result'])
        result['issues'][0].update(source_file_id=file_id, original_text='synthetic content')
        store.save_result(run, result)
        with store.connect() as db:
            db.execute('UPDATE runs SET snapshot=? WHERE id=?', (json.dumps({'files': files}), run))
        _, paths = generate_annotations(store, run, [1], tmp_path)
        assert len(paths) == 1
        path = Path(paths[0])
    result = json.loads(store.run(run)['result'])
    assert result['delivery_versions'][str(path.resolve())]['sha256'] == digest(path)
    store.append(session, 'assistant', 'delivery done')
    service = SessionService(store)
    child = service.fork(session, store.messages(session)[-1]['id'], 'child')
    assert len(service.branch_results(child)) == 1
    path.write_bytes(b'synthetic replacement')
    with pytest.raises(ValueError):
        service.branch_results(child)


@pytest.mark.parametrize('versions', [[], None, 'invalid'])
def test_invalid_version_metadata_is_rejected(tmp_path, versions):
    from asset_based_agent.technical_platform.delivery_versions import (
        verify_review_deliveries,
    )
    path = tmp_path / 'synthetic.docx'
    path.write_bytes(b'synthetic')
    with pytest.raises(TypeError):
        verify_review_deliveries({'exported_report': str(path), 'delivery_versions': versions})


@pytest.mark.parametrize('kind', ['report', 'annotation'])
def test_compound_review_delivery_versions_are_verified(tmp_path, monkeypatch, kind):
    from test_step_delivery import reviewed

    from asset_based_agent.technical_platform.annotations import generate_annotations
    from asset_based_agent.technical_platform.report_export import export_review
    from asset_based_agent.technical_platform.review_delivery import step_review_store
    store, session, run = reviewed(tmp_path, monkeypatch, with_issues=True)
    view = step_review_store(store, session, run, 1)
    if kind == 'report':
        path = export_review(view, run, tmp_path / 'compound.docx')
    else:
        _, paths = generate_annotations(view, run, [1], tmp_path)
        assert len(paths) == 1
        path = Path(paths[0])
    store.append(session, 'assistant', 'delivered')
    service = SessionService(store)
    child = service.fork(session, store.messages(session)[-1]['id'], 'child')
    assert len(service.branch_results(child)) == 1
    path.unlink()
    with pytest.raises(ValueError):
        service.branch_results(child)
