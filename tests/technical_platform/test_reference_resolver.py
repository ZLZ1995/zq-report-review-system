import pytest
from test_file_scope import fileset


def test_same_name_is_ambiguous_not_latest_file_guess(tmp_path):
    from asset_based_agent.technical_platform.reference_resolver import resolve_file
    store, _, session, files = fileset(tmp_path)
    result = resolve_file(store, session, {'name': '报告.docx'},
                          candidate_ids=[f['id'] for f in files])
    assert result.status == 'ambiguous'
    assert set(result.candidate_ids) == {f['id'] for f in files}
    assert result.file_id is None


def test_explicit_version_resolves_only_inside_current_candidates(tmp_path):
    from asset_based_agent.technical_platform.reference_resolver import resolve_file
    store, _, session, files = fileset(tmp_path)
    result = resolve_file(store, session, {'name': '报告.docx', 'sha256': files[0]['sha256']},
                          candidate_ids=[f['id'] for f in files])
    assert result.file_id == files[0]['id'] and result.status == 'resolved'
    outside = resolve_file(store, session, {'id': files[1]['id']},
                           candidate_ids=[files[0]['id']])
    assert outside.status == 'missing' and outside.file_id is None
    assert resolve_file(store, session, {'name': '报告'},
                        candidate_ids=[files[0]['id']]).status == 'missing'


def test_unknown_scope_and_cross_owner_cannot_expand_candidates(tmp_path):
    from asset_based_agent.technical_platform.reference_resolver import resolve_file
    from asset_based_agent.technical_platform.store import PlatformStore
    store, _, session, files = fileset(tmp_path)
    with pytest.raises(PermissionError):
        resolve_file(store, session, {'name': '报告.docx'}, candidate_ids=['unknown'])
    with pytest.raises(PermissionError):
        resolve_file(PlatformStore(store.path, 'bob'), session, {'id': files[0]['id']},
                     candidate_ids=[files[0]['id']])
    with pytest.raises(ValueError):
        resolve_file(store, session, {'path': 'D:/secret.docx'}, candidate_ids=[])
