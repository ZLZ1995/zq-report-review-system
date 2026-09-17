import json
from threading import Event

from asset_based_agent.technical_platform.browser_task_leases import BrowserTaskLeases
from asset_based_agent.technical_platform.task_manager import TaskBinding, TaskManager
from tests.technical_platform.test_browser_trusted_login import setup


def bound(*, can_click=None, can_edit=None, can_scroll=None, can_download=None, can_upload=None):
    from asset_based_agent.technical_platform.browser_observer import BrowserObserver
    _, page, session, _ = setup()
    manager = TaskManager()
    binding = TaskBinding('alice', 'p', 's', 't')
    from types import SimpleNamespace
    worker = SimpleNamespace(cancel=Event(), isRunning=lambda: True)
    manager.register(binding, worker)
    leases = BrowserTaskLeases(session, manager); leases.register(page)
    lease = leases.acquire(page, binding, worker, confirmed=True)
    allowed = [True]
    observer = BrowserObserver(leases, page, can_observe=lambda *_: allowed[0], can_click=can_click, can_edit=can_edit,
                               can_scroll=can_scroll, can_download=can_download, can_upload=can_upload)
    return observer, leases, lease, page, allowed


def respond(page, **updates):
    script, world, callback = page.calls[-1]
    assert world == 1
    nonce = json.loads(script.rsplit(')(', 1)[1][:-1])
    payload = {'nonce': nonce, 'origin': 'https://example.com', 'text': 'Visible',
               'controls': [], 'truncated': False}
    payload.update(updates)
    callback(json.dumps(payload))


def test_observer_returns_typed_untrusted_content_only_for_owned_lease():
    observer, leases, lease, page, allowed = bound()
    results = []; observer.observe(lease, results.append); respond(page)
    assert results[0].text == 'Visible' and results[0].untrusted is True
    allowed[0] = False
    before = len(page.calls)
    observer.observe(lease, results.append)
    assert results[-1] is None and len(page.calls) == before
    allowed[0] = True; leases.takeover(page)
    observer.observe(lease, results.append)
    assert results[-1] is None and len(page.calls) == before


def test_late_or_malformed_observations_are_discarded():
    for change in ('navigation', 'takeover', 'permission', 'schema', 'origin', 'closed'):
        observer, leases, lease, page, allowed = bound()
        results=[]; observer.observe(lease, results.append)
        if change=='navigation': page.loadStarted.emit()
        elif change=='takeover': leases.takeover(page)
        elif change=='permission': allowed[0]=False
        elif change=='closed': observer.close()
        respond(page, **({'extra':'forbidden'} if change=='schema' else
                         {'origin':'https://other.test'} if change=='origin' else {}))
        assert results==[None], change


def test_click_requires_explicit_native_action_gate_and_one_observation():
    permitted = [False]
    observer, _, lease, page, _ = bound(can_click=lambda *_: permitted[0])
    observed=[]; observer.observe(lease,observed.append)
    respond(page, controls=[{'id':'1','kind':'button','text':'Upload','disabled':False}])
    before=len(page.calls); result=[]
    observer.click(lease,observed[0],'1',callback=result.append)
    assert result==['rejected'] and len(page.calls)==before
    permitted[0] = True
    observed=[]; observer.observe(lease,observed.append)
    respond(page, controls=[{'id':'1','kind':'button','text':'Upload','disabled':False}])
    observer.click(lease,observed[0],'1',callback=result.append)
    page.calls[-1][2]('{"status":"dispatched"}')
    assert result[-1]=='dispatched'
    observer.click(lease,observed[0],'1',callback=result.append)
    assert result[-1]=='rejected'


def test_click_late_reply_after_takeover_is_unknown_not_success():
    observer, leases, lease, page, _ = bound(can_click=lambda *_: True)
    observed=[]; observer.observe(lease,observed.append)
    respond(page, controls=[{'id':'1','kind':'button','text':'Upload','disabled':False}])
    result=[]; observer.click(lease,observed[0],'1',callback=result.append)
    leases.takeover(page)
    page.calls[-1][2]('{"status":"dispatched"}')
    assert result==['unknown']


def test_takeover_during_confirmation_never_dispatches():
    def gate(*_):
        leases.takeover(page)
        return True
    observer, leases, lease, page, _ = bound(can_click=gate)
    observed=[]; observer.observe(lease,observed.append)
    respond(page, controls=[{'id':'1','kind':'button','text':'Upload','disabled':False}])
    before=len(page.calls); result=[]
    observer.click(lease,observed[0],'1',callback=result.append)
    assert result==['rejected'] and len(page.calls)==before


def test_edit_requires_separate_gate_binding_value_and_operation():
    permits=[]
    def gate(lease, observation, control, operation, value):
        permits.append((control.id, operation, value))
        return value=='Approved name'
    observer, _, lease, page, _ = bound(can_edit=gate)
    for value, expected in [('Denied','rejected'),('Approved name','dispatched')]:
        observed=[]; observer.observe(lease,observed.append)
        respond(page, controls=[{'id':'1','kind':'textfield','text':'Project','disabled':False}])
        assert observed[0] is not None
        result=[]; observer.edit(lease,observed[0],'1','fill',value,callback=result.append)
        if expected=='dispatched': page.calls[-1][2]('{"status":"dispatched"}')
        assert result==[expected]
    assert permits==[('1','fill','Denied'),('1','fill','Approved name')]


def test_edit_unknown_option_and_wrong_control_kind_never_dispatch():
    observer, _, lease, page, _ = bound(can_edit=lambda *_:True)
    for operation,value in [('select','2'),('fill','anything')]:
        observed=[]; observer.observe(lease,observed.append)
        respond(page, controls=[{'id':'1','kind':'select','text':'Category','disabled':False,
                                'options':[{'id':'1','text':'Alpha'}]}])
        before=len(page.calls); result=[]
        observer.edit(lease,observed[0],'1',operation,value,callback=result.append)
        assert result==['rejected'] and len(page.calls)==before


def test_scroll_is_scoped_single_observation_and_cancel_safe():
    for scenario in ('allowed', 'denied', 'takeover', 'navigation'):
        observer, leases, lease, page, _ = bound(can_scroll=lambda *_, case=scenario: case != 'denied')
        observed=[]; observer.observe(lease, observed.append); respond(page)
        if scenario == 'takeover': leases.takeover(page)
        if scenario == 'navigation': page.loadStarted.emit()
        before=len(page.calls); results=[]
        observer.scroll(lease, observed[0], 'down', callback=results.append)
        if scenario == 'allowed':
            assert len(page.calls)==before+1
            page.calls[-1][2]('{"status":"dispatched"}')
            assert results==['dispatched']
            observer.scroll(lease, observed[0], 'down', callback=results.append)
            assert results[-1]=='rejected'
        else:
            assert results==['rejected'] and len(page.calls)==before


def test_download_resolution_is_one_use_and_requires_its_own_gate():
    for permit in (False, True):
        observer, _, lease, page, _ = bound(can_click=lambda *_:True, can_download=lambda *_, permit=permit:permit)
        observed=[]; observer.observe(lease, observed.append)
        respond(page, controls=[{'id':'1','kind':'link','text':'Download','disabled':False}])
        result=[]; before=len(page.calls)
        observer.resolve_download(lease, observed[0], '1', callback=result.append)
        if permit:
            page.calls[-1][2]('{"status":"resolved","url":"https://example.com/file"}')
            assert result==['https://example.com/file']
            observer.resolve_download(lease, observed[0], '1', callback=result.append)
            assert result[-1] is None
        else: assert result==[None] and len(page.calls)==before


def test_upload_observation_requires_scope_and_single_native_reservation():
    permitted = [True]
    observer, _, lease, page, _ = bound(can_upload=lambda *_: permitted[0])
    observed = []
    observer.observe(lease, observed.append)
    script, world, callback = page.calls[-1]
    assert world == 1 and script.endswith(',true)')
    nonce = json.loads(script.rsplit(')(', 1)[1][:-6])
    callback(json.dumps({'nonce': nonce, 'origin': 'https://example.com', 'text': 'Upload',
        'controls': [{'id': '1', 'kind': 'file', 'text': 'Artifact', 'disabled': False}], 'truncated': False}))
    assert observer.reserve_upload(lease, observed[0], '1') is True
    assert observer.reserve_upload(lease, observed[0], '1') is False
    permitted[0] = False
    observer.observe(lease, observed.append)
    respond(page, controls=[{'id': '1', 'kind': 'file', 'text': 'Artifact', 'disabled': False}])
    assert observer.reserve_upload(lease, observed[-1], '1') is False


def test_download_button_captures_only_after_native_gate_and_before_script():
    for allowed in (False, True):
        order=[]
        def gate(*_, order=order, allowed=allowed):
            order.append('confirm')
            return allowed
        observer, _, lease, page, _ = bound(can_download=gate)
        observed=[]; observer.observe(lease, observed.append)
        respond(page, controls=[{'id':'1','kind':'button','text':'Download','disabled':False}])
        before=len(page.calls); results=[]
        def capture(page=page, before=before, order=order):
            assert len(page.calls)==before
            order.append('capture'); return True
        observer.download_button(lease, observed[0], '1', before_dispatch=capture, callback=results.append)
        if allowed:
            assert order==['confirm','capture'] and len(page.calls)==before+1
            page.calls[-1][2]('{"status":"dispatched"}')
            assert results==['dispatched']
        else:
            assert order==['confirm'] and results==['rejected']
