"""Conservative local checkpoint reconciliation; never restarts a business tool."""
from .event_store import ExecutionStore


def reconcile_execution(store, run_id):
    events = ExecutionStore(store)
    with store.connect() as db:
        run = events._run(db, run_id)
        steps = db.execute('SELECT state,claim_token FROM execution_steps WHERE run=?',
                           (run_id,)).fetchall()
    if not steps:
        return 'legacy_or_not_started'
    if len(steps) != 1:
        if run['state'] == 'succeeded':
            from .plan_results import completed_step_results
            try:
                completed_step_results(store, run['session'], run_id)
                return 'succeeded'
            except (ValueError, PermissionError, KeyError, TypeError):
                pass  # Missing evidence remains reconciliation-required; never replay.
        return 'reconciliation_required'
    if run['state'] not in {'succeeded', 'failed', 'cancelled'}:
        # A heartbeat timeout alone proves neither process death nor remote failure.
        return 'reconciliation_required'
    if steps[0]['state'] == 'running' and steps[0]['claim_token']:
        events.record_run_terminal(run_id, steps[0]['claim_token'])
        return run['state']
    if steps[0]['state'] == run['state']:
        return run['state']
    return 'reconciliation_required'
