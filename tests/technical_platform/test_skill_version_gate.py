"""A queued generation cannot adopt changed instructions without reconfirmation."""
import threading

import pytest

from asset_based_agent.technical_platform import generation
from asset_based_agent.technical_platform.execution import execute_task
from asset_based_agent.technical_platform.skills import DETAIL, HISTORY, digest
from asset_based_agent.technical_platform.store import PlatformStore
from asset_based_agent.technical_platform.task_spec import build_task_spec


@pytest.mark.parametrize('skill', [DETAIL, HISTORY])
def test_queued_generation_blocks_changed_bundle_before_model_or_outputs(tmp_path, monkeypatch, skill):
    store = PlatformStore(tmp_path / 'project.sqlite', 'alice')
    project = store.create_project('synthetic')
    session = store.create_session(project)
    source = tmp_path / 'synthetic.xlsx'
    source.write_bytes(b'synthetic placeholder; parser must not be reached')
    original = digest(source)
    store.add_file(project, source, original)
    files = store.files(project)
    monkeypatch.setattr(generation, 'bundle_fingerprint', lambda _: 'a' * 64)
    snapshot = build_task_spec(
        store, session, 'Generate using these selected synthetic files', skill, files,
        model='synthetic-model' if skill == DETAIL else None,
        input_roles=None if skill == DETAIL else {'source_excel': files[0]['id']},
        generation_confirmed=True,
    ).to_snapshot()
    run = store.start_run(session, snapshot)
    from asset_based_agent.technical_platform.permissions import PermissionService
    PermissionService(store).authorize(run, snapshot, confirmed=True)
    monkeypatch.setattr(generation, 'bundle_fingerprint', lambda _: 'b' * 64)
    calls = []

    class Provider:
        model_id = 'synthetic-model'
        skill_instructions = 'a' * 64

        def analyze(self, *args):
            calls.append(args)
            raise AssertionError('Model must not be reached')

    with pytest.raises(PermissionError, match='生成规则'):
        execute_task(store, run, threading.Event(), lambda _: None,
                     provider=Provider() if skill == DETAIL else None)
    assert calls == []
    assert store.run(run)['state'] == 'failed'
    assert not (tmp_path / 'runs' / run).exists()
    assert digest(source) == original
