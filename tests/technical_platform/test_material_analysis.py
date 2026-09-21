import pytest


@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_analysis_rejects_unknown_file_and_ambiguous_role():
    from asset_based_agent.technical_platform.material_analysis import resolve_roles
    with pytest.raises(ValueError):
        resolve_roles({'assignments': [{'file_id': 'outside', 'role': 'balance_sheet'}]}, [{'id': 'one'}])
    with pytest.raises(ValueError):
        resolve_roles({'assignments': [{'file_id': 'one', 'role': 'balance_sheet'},
                                       {'file_id': 'two', 'role': 'balance_sheet'}]},
                      [{'id': 'one'}, {'id': 'two'}])


def test_analysis_does_not_require_trial_balance_or_journal():
    from asset_based_agent.technical_platform.material_analysis import resolve_roles
    assert resolve_roles({'assignments': [{'file_id': 'one', 'role': 'balance_sheet'},
                                          {'file_id': 'two', 'role': 'bank_statement'}]},
                         [{'id': 'one'}, {'id': 'two'}]) == {'balance_sheet': 'one', 'bank_statement': 'two'}


def test_detail_dialog_has_no_manual_role_selectors(qapp, tmp_path):
    from PySide6.QtWidgets import QComboBox

    from asset_based_agent.technical_platform.generation_dialog import GenerationDialog
    from asset_based_agent.technical_platform.skills import DETAIL
    dialog = GenerationDialog(DETAIL, [{'id': 'one', 'name': 'material.xlsx'}], tmp_path)
    assert not dialog.findChildren(QComboBox)
    dialog.consent.setChecked(True)
    dialog.confirm()
    assert dialog.roles is None


def test_provider_uploads_visible_excerpt_not_paths_or_hidden_sheets(tmp_path):
    from threading import Event

    from openpyxl import Workbook

    from asset_based_agent.technical_platform.material_analysis import (
        MaterialAnalysisProvider,
    )
    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / 'sample.xlsx'
    wb = Workbook()
    wb.active['A1'] = '资产负债表'
    wb.create_sheet('hidden')['A1'] = 'NEVER_UPLOAD_SECRET'
    wb['hidden'].sheet_state = 'hidden'
    wb.save(path)
    class Client:
        def analyze_materials(self, payload):
            assert 'NEVER_UPLOAD_SECRET' not in str(payload)
            assert str(tmp_path) not in str(payload)
            assert '资产负债表' in payload['files'][0]['text']
            return {'assignments': [{'file_id': 'one', 'role': 'balance_sheet', 'reason': '表头'}]}
    resolution, _ = MaterialAnalysisProvider(Client(), 'model', 'rules').analyze(
        [{'id': 'one', 'name': path.name, 'path': str(path), 'sha256': digest(path)}],
        'run', Event(), lambda _: None)
    assert resolution.selected == {'balance_sheet': 'one'}


def test_auto_generation_task_authorizes_only_model_analysis_and_copy_writes(tmp_path, monkeypatch):
    from threading import Event

    from asset_based_agent.technical_platform import generation
    from asset_based_agent.technical_platform.execution import execute_task
    from asset_based_agent.technical_platform.material_analysis import (
        MaterialAnalysisProvider,
    )
    from asset_based_agent.technical_platform.skills import DETAIL, digest
    from asset_based_agent.technical_platform.store import PlatformStore
    from asset_based_agent.technical_platform.task_spec import build_task_spec
    source = tmp_path / 'source.xlsx'
    source.write_bytes(b'fixture')
    store = PlatformStore(tmp_path / 'platform.sqlite', 'user')
    project = store.create_project('test')
    session = store.create_session(project)
    store.add_file(project, source, digest(source))
    spec = build_task_spec(store, session, '生成明细表', DETAIL, store.files(project),
                           model='model', generation_confirmed=True).to_snapshot()
    assert spec['input_roles'] is None
    assert spec['permissions']['call_model'] is True
    assert spec['permissions']['modify_originals'] is False
    assert spec['permissions']['upload_raw_files'] is False
    provider = MaterialAnalysisProvider(None, 'model', spec['skill_instructions'])
    def execute(*args, **kwargs):
        assert kwargs['provider'] is provider
        assert kwargs['manage_run'] is False
        return {'kind': 'generation', 'ok': False, 'artifacts': [], 'feedback': 'synthetic blocked', 'model_called': True}
    monkeypatch.setattr(generation, 'execute_generation', execute)
    run = store.start_run(session, spec)
    from asset_based_agent.technical_platform.permissions import PermissionService
    PermissionService(store).authorize(run, spec, confirmed=True)
    result = execute_task(store, run, Event(), lambda _: None, provider=provider)
    assert result['feedback'] == 'synthetic blocked'
    assert result['ok'] is False
    assert store.run(run)['state'] == 'failed'


def test_provider_bounds_per_file_excerpt_for_server_output_budget(tmp_path):
    from threading import Event

    from openpyxl import Workbook

    from asset_based_agent.technical_platform.material_analysis import (
        MAX_FILE_EXCERPT_CHARS,
        MaterialAnalysisProvider,
    )
    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / 'long.xlsx'
    wb = Workbook()
    ws = wb.active
    ws['A1'] = '资产负债表'
    for row in range(2, 400):
        ws.cell(row, 1, f'科目{row:03d}')
        ws.cell(row, 2, row * 100)
    wb.save(path)
    captured = {}

    class Client:
        def analyze_materials(self, payload):
            captured.update(payload)
            return {'assignments': [{'file_id': 'one', 'role': 'balance_sheet', 'reason': '表头'}]}

    resolution, _ = MaterialAnalysisProvider(Client(), 'model', 'rules').analyze(
        [{'id': 'one', 'name': path.name, 'path': str(path), 'sha256': digest(path)}],
        'run', Event(), lambda _: None)
    assert resolution.selected == {'balance_sheet': 'one'}
    assert 0 < len(captured['files'][0]['text']) <= MAX_FILE_EXCERPT_CHARS
    assert MAX_FILE_EXCERPT_CHARS <= 1500


def test_provider_retries_once_on_incomplete_server_result(tmp_path):
    from threading import Event

    from openpyxl import Workbook

    from asset_based_agent.report_review_app.services.remote_auth_service import (
        RemoteAuthenticationError,
        SessionRevoked,
    )
    from asset_based_agent.technical_platform.material_analysis import (
        MaterialAnalysisProvider,
    )
    from asset_based_agent.technical_platform.skills import digest
    path = tmp_path / 'sample.xlsx'
    wb = Workbook()
    wb.active['A1'] = '资产负债表'
    wb.save(path)
    files = [{'id': 'one', 'name': path.name, 'path': str(path), 'sha256': digest(path)}]

    class FlakyClient:
        calls = 0

        def analyze_materials(self, payload):
            FlakyClient.calls += 1
            if FlakyClient.calls <= 2:
                raise RemoteAuthenticationError('资料识别结果不完整，请重试；没有生成文件。')
            return {'assignments': [{'file_id': 'one', 'role': 'balance_sheet', 'reason': '表头'}]}

    resolution, _ = MaterialAnalysisProvider(FlakyClient(), 'model', 'rules').analyze(
        files, 'run', Event(), lambda _: None)
    assert resolution.selected == {'balance_sheet': 'one'}
    assert FlakyClient.calls == 3

    class AlwaysBadClient:
        calls = 0

        def analyze_materials(self, payload):
            AlwaysBadClient.calls += 1
            raise RemoteAuthenticationError('资料识别结果不完整，请重试；没有生成文件。')

    with pytest.raises(RemoteAuthenticationError):
        MaterialAnalysisProvider(AlwaysBadClient(), 'model', 'rules').analyze(
            files, 'run', Event(), lambda _: None)
    assert AlwaysBadClient.calls == 3

    class RevokedClient:
        calls = 0

        def analyze_materials(self, payload):
            RevokedClient.calls += 1
            raise SessionRevoked('当前没有有效登录会话。')

    with pytest.raises(SessionRevoked):
        MaterialAnalysisProvider(RevokedClient(), 'model', 'rules').analyze(
            files, 'run', Event(), lambda _: None)
    assert RevokedClient.calls == 1
