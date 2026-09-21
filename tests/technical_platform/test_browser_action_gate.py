from test_browser_action_receipts import ready
from test_browser_observer import bound, respond


def connected(tmp_path, confirm):
    from asset_based_agent.technical_platform.browser_action_gate import (
        BrowserActionGate,
    )
    store, run, service, request = ready(tmp_path)
    observer, leases, lease, page, _ = bound()
    # Use the real database task identity for the native live worker binding.
    from asset_based_agent.technical_platform.task_manager import TaskBinding
    binding = TaskBinding(request.identity.owner, request.identity.project_id,
                          request.identity.session_id, run)
    leases.takeover(page)
    from threading import Event
    from types import SimpleNamespace
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    leases.manager.register(binding, worker)
    lease = leases.acquire(page, binding, worker, confirmed=True)
    current = [request]
    gate = BrowserActionGate(service, leases, resolve=lambda _: current[0], confirm=confirm)
    observer._can_edit = gate.edit
    observed = []
    observer.observe(lease, observed.append)
    respond(page, controls=[{'id':'1','kind':'textfield','text':'Project','disabled':False}])
    return store, observer, leases, lease, page, observed[0], current


def test_observer_edit_consumes_durable_receipt_before_dispatch(tmp_path):
    confirmations = []
    def confirm(request, control, value):
        confirmations.append((request.action, control.text, value))
        return True
    store, observer, _, lease, page, observation, _ = connected(tmp_path, confirm)
    result = []
    observer.edit(lease, observation, '1', 'fill', 'Approved', callback=result.append)
    with store.connect() as db:
        rows = db.execute('SELECT consumed FROM browser_action_authorizations').fetchall()
        assert [r[0] for r in rows] == [1]
    page.calls[-1][2]('{"status":"dispatched"}')
    assert result == ['dispatched']
    assert confirmations == [('fill', 'Project', 'Approved')]


def test_decline_and_changed_claim_during_confirmation_do_not_dispatch(tmp_path):
    holder = {}
    def confirm(*_):
        holder['current'][0] = holder['current'][0].model_copy(update={'claim_token':'changed'})
        return True
    store, observer, _, lease, page, observation, current = connected(tmp_path, confirm)
    holder['current'] = current
    before = len(page.calls); result = []
    observer.edit(lease, observation, '1', 'fill', 'Approved', callback=result.append)
    assert result == ['rejected'] and len(page.calls) == before
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM browser_action_authorizations').fetchone()[0] == 0


def test_declined_action_never_creates_receipt(tmp_path):
    store, observer, _, lease, page, observation, _ = connected(tmp_path, lambda *_: False)
    before = len(page.calls); result = []
    observer.edit(lease, observation, '1', 'fill', 'Approved', callback=result.append)
    assert result == ['rejected'] and len(page.calls) == before
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM browser_action_authorizations').fetchone()[0] == 0


def test_environment_mismatch_never_prompts_or_dispatches(tmp_path):
    prompts = []
    _, observer, leases, lease, page, observation, _ = connected(
        tmp_path, lambda *_: prompts.append(True) or True)
    leases.session.environment = 'production'
    before = len(page.calls); result = []
    observer.edit(lease, observation, '1', 'fill', 'Approved', callback=result.append)
    assert result == ['rejected'] and len(page.calls) == before and not prompts


def test_takeover_during_confirmation_creates_no_receipt(tmp_path):
    holder = {}
    def confirm(*_):
        holder['leases'].takeover(holder['page'])
        return True
    store, observer, leases, lease, page, observation, _ = connected(tmp_path, confirm)
    holder.update(leases=leases, page=page)
    before = len(page.calls); result = []
    observer.edit(lease, observation, '1', 'fill', 'Approved', callback=result.append)
    assert result == ['rejected'] and len(page.calls) == before
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM browser_action_authorizations').fetchone()[0] == 0
