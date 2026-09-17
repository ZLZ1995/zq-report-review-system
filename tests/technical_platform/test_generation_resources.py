from threading import Event, Thread
from types import SimpleNamespace

from asset_based_agent.report_review_app.services.resource_locks import CLIENT_RESOURCES
from asset_based_agent.report_review_app.services.task_cancellation import TaskCancelled
from asset_based_agent.technical_platform import generation
from asset_based_agent.technical_platform.skills import DETAIL, digest


def test_office_queue_cancel_never_starts_generation_process(tmp_path, monkeypatch):
    source = tmp_path / 'synthetic.xlsx'
    source.write_bytes(b'synthetic-input')
    balance = tmp_path / 'balance.xlsx'
    balance.write_bytes(b'synthetic-balance')
    template = tmp_path / 'template.xlsx'
    template.write_bytes(b'synthetic-template')
    monkeypatch.setattr(generation, 'bundle_fingerprint', lambda _: 'rules')
    monkeypatch.setattr(generation, 'locked_template', lambda _: template)
    started = []
    monkeypatch.setattr(generation.subprocess, 'Popen', lambda *a, **kw: started.append(True))
    files = [{'id': identity, 'name': path.name, 'path': str(path), 'sha256': digest(path)}
             for identity, path in [('source', source), ('balance', balance)]]
    snapshot = {'skill_id': DETAIL.id, 'files': files, 'input_roles': {
        'trial_balance': 'source', 'balance_sheet': 'balance'}, 'mode': 'local_generation',
        'skill_instructions': 'rules', 'capabilities': ['generate_artifacts', 'read_selected_files']}
    waiting, cancel, done = Event(), Event(), Event()
    result, errors = [], []
    def progress(message):
        if '等待本地生成资源' in message:
            waiting.set()
    def run():
        try:
            generation.execute_generation(SimpleNamespace(path=tmp_path / 'state.sqlite'),
                'synthetic-run', snapshot, cancel, progress, manage_run=False)
        except TaskCancelled:
            result.append('cancelled')
        except Exception as exc:  # noqa: BLE001 - asserted on the owning test thread
            errors.append(exc)
        finally:
            done.set()
    with CLIENT_RESOURCES.lease(('office',)):
        worker = Thread(target=run)
        worker.start()
        try:
            assert waiting.wait(3), errors
            cancel.set()
            assert done.wait(3)
            assert result == ['cancelled']
            assert not errors
            assert not started
        finally:
            cancel.set()
            worker.join(3)
    assert source.read_bytes() == b'synthetic-input'
    assert template.read_bytes() == b'synthetic-template'
