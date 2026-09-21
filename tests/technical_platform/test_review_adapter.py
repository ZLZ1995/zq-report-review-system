import json
import threading

import pytest
from test_execution import make_run
from test_harness import compound


def test_two_real_preflights_keep_step_results_and_originals(tmp_path):
    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.step_results import StepResults
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    adapter = ReviewAdapter(store, run, progress=lambda _: None)
    assert execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': adapter}), threading.Event()) == 'succeeded'
    outputs = json.loads(store.run(run)['result'])['steps']
    assert outputs['execute']['result_ref'] != outputs['second']['result_ref']
    for step_id, output in outputs.items():
        result = StepResults(store).read(run, step_id, output['result_ref'])
        assert result['kind'] == 'preflight'
        assert result['files'][0]['chunks'] > 0
        assert result['model_called'] is False
        assert 'DO_NOT_UPLOAD' not in str(result)


def test_real_review_adapter_uses_filtered_batches_and_step_idempotency(tmp_path):
    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, _ = make_run(tmp_path, remote=True)
    plan = ExecutionPlan.model_validate(json.loads(store.run(run)['snapshot'])['execution_plan'])
    calls = []
    class Provider:
        model_id = 'test'
        skill_instructions = 'rules'
        def set_client_job_id(self, identity):
            assert identity == f'PLATFORM-{run}-execute'
        def review_batches(self, batches, progress_callback=None):
            assert 'DO_NOT_UPLOAD' not in str(batches)
            calls.append(batches)
            return []
    adapter = ReviewAdapter(store, run, provider=Provider(), progress=lambda _: None)
    assert execute_plan(store, run, plan, ToolDispatcher({'review.execute': adapter}), threading.Event()) == 'succeeded'
    assert len(calls) == 1


def test_real_review_adapter_persists_normalized_issue_evidence(tmp_path):
    from asset_based_agent.report_review_app.services.rule_registry import (
        IssueCandidate,
    )
    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.step_results import StepResults
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher

    store, run, _ = make_run(tmp_path, remote=True)
    plan = ExecutionPlan.model_validate(json.loads(store.run(run)['snapshot'])['execution_plan'])
    source = json.loads(store.run(run)['snapshot'])['files'][0]
    candidate = IssueCandidate(
        source_file_id=source['id'], source_file_name=source['name'], category='synthetic',
        risk_level='medium', location={'paragraph': 1}, description='Synthetic issue',
        confidence=0.8, evidence_summaries=['paragraph 1'],
    )
    class Provider:
        model_id = 'test'
        skill_instructions = 'rules'
        def set_client_job_id(self, _):
            pass
        def review_batches(self, batches, progress_callback=None):
            return [candidate, candidate]
    adapter = ReviewAdapter(store, run, provider=Provider(), progress=lambda _: None)
    assert execute_plan(store, run, plan, ToolDispatcher({'review.execute': adapter}),
                        threading.Event()) == 'succeeded'
    with store.connect() as db:
        identity = db.execute('SELECT id FROM execution_results WHERE run=?', (run,)).fetchone()[0]
    result = StepResults(store).read(run, 'execute', identity)
    assert len(result['issues']) == 1
    assert result['issues'][0]['evidence_state'] == 'sufficient'
    assert len(result['issues'][0]['fingerprint']) == 64


def test_step_result_cannot_be_read_by_another_account(tmp_path):
    from asset_based_agent.technical_platform.step_results import StepResults
    from asset_based_agent.technical_platform.store import PlatformStore
    store, run, _ = make_run(tmp_path)
    with pytest.raises(PermissionError):
        StepResults(PlatformStore(store.path, 'bob')).read(run, 'execute', 'anything')


def test_changed_source_never_publishes_step_result(tmp_path):
    from pathlib import Path

    from asset_based_agent.technical_platform.adapters.review import ReviewAdapter
    from asset_based_agent.technical_platform.harness import execute_plan
    from asset_based_agent.technical_platform.tool_dispatcher import ToolDispatcher
    store, run, plan = compound(tmp_path)
    snapshot = json.loads(store.run(run)['snapshot'])
    Path(snapshot['files'][0]['path']).write_bytes(b'synthetic changed source')
    adapter = ReviewAdapter(store, run, progress=lambda _: None)
    assert execute_plan(store, run, plan, ToolDispatcher({'preflight.execute': adapter}), threading.Event()) == 'failed'
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM execution_results').fetchone()[0] == 0


def test_fake_result_reference_cannot_be_committed(tmp_path):
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.tool_dispatcher import ToolOutcome
    store, run, plan = compound(tmp_path)
    store.claim_run(run)
    events = ExecutionStore(store)
    events.register(plan)
    token = events.claim(run, 'execute')
    with pytest.raises(PermissionError):
        events.finish_step(run, 'execute', token, ToolOutcome(
            step_id='execute', status='succeeded', passed_gates=plan.steps[0].acceptance_gates,
            result_ref='nonexistent'))


def test_step_result_read_detects_corruption(tmp_path):
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.step_results import StepResults
    store, run, plan = compound(tmp_path)
    store.claim_run(run)
    events = ExecutionStore(store)
    events.register(plan)
    events.claim(run, 'execute')
    results = StepResults(store)
    identity = results.save(run, 'execute', {'kind': 'preflight'})
    assert results.save(run, 'execute', {'kind': 'preflight'}) == identity
    with pytest.raises(ValueError):
        results.save(run, 'execute', {'kind': 'different'})
    with store.connect() as db:
        db.execute('UPDATE execution_results SET payload=? WHERE id=?', ('{}', identity))
    with pytest.raises(ValueError):
        results.read(run, 'execute', identity)
