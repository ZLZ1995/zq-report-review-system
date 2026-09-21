import threading

import pytest

from asset_based_agent.technical_platform.execution import execute_task
from asset_based_agent.technical_platform.permissions import PermissionService
from asset_based_agent.technical_platform.skills import HISTORY, digest
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import build_task_spec


def history_run(tmp_path):
    store = PlatformStore(tmp_path / 'state.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    source = tmp_path / 'source.xlsx'
    source.write_bytes(b'synthetic; worker mocked before parsing')
    store.add_file(project, source, digest(source))
    files = store.files(project)
    snapshot = build_task_spec(store, session, 'generate history', HISTORY, files,
                               input_roles={'source_excel': files[0]['id']}, generation_confirmed=True).to_snapshot()
    run = store.start_run(session, snapshot)
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    return store, run


@pytest.mark.parametrize('mode', ['missing', 'outside', 'renamed', 'failed-with-artifact'])
def test_generator_cannot_publish_missing_or_invalid_primary(tmp_path, monkeypatch, mode):
    from asset_based_agent.technical_platform import generation
    store, run = history_run(tmp_path)
    root = tmp_path / 'runs' / run / 'output'
    root.mkdir(parents=True)
    path = (tmp_path if mode == 'outside' else root) / ('other.txt' if mode == 'renamed' else 'history_fragment.docx')
    path.write_bytes(b'synthetic artifact')
    def fake(*args, **kwargs):
        assert kwargs['manage_run'] is False
        return {'kind': 'generation', 'ok': mode != 'failed-with-artifact', 'model_called': False,
                'feedback': 'synthetic', 'artifacts': [] if mode == 'missing' else
                [{'name': 'history_fragment.docx', 'path': str(path), 'sha256': digest(path)}]}
    monkeypatch.setattr(generation, 'execute_generation', fake)
    with pytest.raises(ValueError):
        execute_task(store, run, threading.Event(), lambda _: None)
    assert store.run(run)['state'] == 'failed'
    assert store.run(run)['result'] is None
