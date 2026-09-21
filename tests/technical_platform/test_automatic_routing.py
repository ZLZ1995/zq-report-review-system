import hashlib
import json
import os
import time
import zipfile

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication

from asset_based_agent.technical_platform.app import PlatformWindow
from asset_based_agent.technical_platform.skills import DETAIL
from asset_based_agent.technical_platform.store import PlatformStore


def test_routing_worker_preserves_safe_compatibility_error():
    from asset_based_agent.report_review_app.services.remote_auth_service import (
        ServerCapabilityUnavailable,
    )
    from asset_based_agent.technical_platform.routing import RoutingWorker
    class Client:
        def route_skill(self, payload):
            raise ServerCapabilityUnavailable('服务端缺少任务接口，请联系管理员升级。')
    worker = RoutingWorker(Client(), 'model', 'synthetic')
    worker.run()
    assert worker.plan is None
    assert '接口' in worker.error
    assert '网络' not in worker.error


def test_dialogue_routes_without_skill_selector(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.db', 'test')
    project = store.create_project('路由')
    store.create_session(project)
    class Client:
        def understand_task(self, payload, *, cancel=None):
            assert payload['prompt'] == '根据资料生成评估明细表'
            assert 'path' not in str(payload['files'])
            return {'schema_version': 1, 'message_intent': 'execute', 'goal': '生成评估明细表',
                    'targets': [payload['files'][0]['id']], 'references': [], 'excluded': [],
                    'constraints': [], 'deliverables': ['明细表'], 'missing_inputs': [],
                    'evidence_message_ids': [payload['message_id']], 'skill_ids': [DETAIL.id],
                    'next_action': 'plan', 'reply': '将根据本轮资料生成明细表。'}
    window = PlatformWindow(store, client=Client(), models=[{'model_id': 'm', 'display_name': '模型'}])
    window.reload_projects(project)
    source = tmp_path / 'data.xlsx'
    source.write_bytes(b'fixture')
    window.import_files([source])
    calls = []
    window.execute_plan = lambda prompt, spec, **kwargs: calls.append((prompt, spec.id))
    try:
        assert not hasattr(window, 'skill_combo')
        window.composer.setPlainText('根据资料生成评估明细表')
        window.submit()
        deadline = time.monotonic() + 5
        while window.worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        assert calls == [('根据资料生成评估明细表', DETAIL.id)]
    finally:
        window.client = None
        window.close()


def test_consultation_without_files_reaches_understanding_and_reply(tmp_path):
    app = QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.db', 'test')
    project = store.create_project('咨询')
    session = store.create_session(project)
    class Client:
        def understand_task(self, payload, *, cancel=None):
            assert payload['files'] == []
            return {'schema_version': 1, 'message_intent': 'consult', 'goal': '',
                    'targets': [], 'references': [], 'excluded': [], 'constraints': [],
                    'deliverables': [], 'missing_inputs': [], 'skill_ids': [],
                    'evidence_message_ids': [payload['message_id']],
                    'next_action': 'answer', 'reply': '审核不会修改原文件。'}
    window = PlatformWindow(store, client=Client(), models=[{'model_id': 'm', 'display_name': '模型'}])
    window.reload_projects(project)
    window.execute_plan = lambda *a, **k: (_ for _ in ()).throw(AssertionError('consultation must not execute'))
    try:
        window.composer.setPlainText('审核会修改原文件吗？')
        window.submit()
        deadline = time.monotonic() + 5
        while window.worker is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(.01)
        messages = store.messages(session)
        assert [m['role'] for m in messages] == ['user', 'assistant']
        assert messages[-1]['text'] == '审核不会修改原文件。'
    finally:
        window.client = None
        window.close()


def test_explicit_current_turn_skill_zip_installs_locally_without_model(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from asset_based_agent.technical_platform.skill_installation import (
        SkillInstallation,
    )

    assert QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.db', 'test')
    project = store.create_project('install')
    store.create_session(project)
    package = tmp_path / 'example.zip'
    instructions = b'review only the selected files'
    manifest = {'schema_version': 1, 'id': 'example.review', 'version': '1.0.0',
                'name': 'Example review', 'adapter': 'report.review',
                'capabilities': ['read_selected_files'], 'dependencies': {},
                'files': {'SKILL.md': hashlib.sha256(instructions).hexdigest()}}
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('manifest.json', json.dumps(manifest))
        archive.writestr('SKILL.md', instructions)
    window = PlatformWindow(store)
    window.reload_projects(project)
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        window.import_files([package])
        window.composer.setPlainText('请安装这个 Skill 并注册到平台')
        window.submit()
        versions = SkillInstallation(store).list_versions()
        assert [(row['skill_id'], row['enabled']) for row in versions] == [('example.review', 1)]
        assert store.messages(window.session_id)[-1]['role'] == 'assistant'
    finally:
        window.close()


def test_new_builtin_skills_route_locally_without_cloud_schema_change(tmp_path):
    from asset_based_agent.technical_platform.skills import (
        FINANCIAL_BRIEF,
        WORKFLOW_TO_SKILL,
    )

    assert QApplication.instance() or QApplication([])
    store = PlatformStore(tmp_path / 'state.db', 'test')
    project = store.create_project('local skills')
    store.create_session(project)
    window = PlatformWindow(store)
    window.reload_projects(project)
    calls = []
    window.execute_plan = lambda prompt, spec, **kwargs: calls.append(spec.id)
    try:
        window.composer.setPlainText('根据三期报表生成财务状况简表')
        window.submit()
        window.composer.setPlainText('校验这个办公工作流并制作 Skill')
        window.submit()
        assert calls == [FINANCIAL_BRIEF.id, WORKFLOW_TO_SKILL.id]
    finally:
        window.close()
