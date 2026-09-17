import json
from hashlib import sha256
from types import SimpleNamespace

import pytest
from test_browser_task_spec import make_browser_run
from test_browser_trusted_login import setup


@pytest.mark.parametrize('case', ['fill', 'decline', 'cancel', 'unknown_account', 'revoked'])
def test_native_login_binds_receipt_and_returns_no_credentials(tmp_path, case):
    from asset_based_agent.technical_platform.browser_action_request import (
        BrowserActionRequest,
    )
    from asset_based_agent.technical_platform.browser_native_login import (
        NativeTaskLogin,
    )
    from asset_based_agent.technical_platform.event_store import ExecutionStore
    from asset_based_agent.technical_platform.execution_plan import ExecutionPlan
    from asset_based_agent.technical_platform.permissions import PermissionService
    from asset_based_agent.technical_platform.task_spec import snapshot_identity
    old, page, session, uses=setup(); old.close()
    vault=old.vault
    vault._for_agent_fill=vault._for_fill
    vault.agent_accounts=lambda _: [SimpleNamespace(key='credential',origin='https://example.com',label='s***')]
    store,run,_=make_browser_run(tmp_path,actions=['observe','login'])
    snapshot=json.loads(store.run(run)['snapshot']); identity=snapshot_identity(snapshot)
    plan=ExecutionPlan.model_validate(snapshot['execution_plan'])
    store.transition(run,'running','test'); events=ExecutionStore(store); events.register(plan)
    claim=events.claim(run,plan.steps[0].step_id); service=PermissionService(store)
    enabled=[True]
    def active():
        service.verify(run)
        return enabled[0]
    requests=[]
    def request(**kwargs):
        requests.append(kwargs)
        return BrowserActionRequest(identity=identity,step_id=plan.steps[0].step_id,revision=1,
            claim_token=claim,environment='test',tab_id='tab',page_version=kwargs['page_version'],
            origin=kwargs['origin'],action=kwargs['action'],target='native',
            payload_sha256=sha256(kwargs['payload'].encode()).hexdigest())
    native=SimpleNamespace(page=page,leases=SimpleNamespace(session=session),lease=SimpleNamespace(tab_id='tab'),
        identity=identity,scope=SimpleNamespace(environment='test'),host=SimpleNamespace(plan=plan),service=service,
        allowed=lambda action,origin:action=='login' and origin=='https://example.com' and active(),request=request)
    def choose(origin,accounts,is_active):
        assert origin=='https://example.com' and is_active()
        assert accounts[0].label=='s***'
        if case=='cancel': enabled[0]=False
        if case=='revoked': service.revoke(run)
        return None if case=='decline' else 'unknown' if case=='unknown_account' else 'credential'
    adapter=NativeTaskLogin(native,SimpleNamespace(_epoch=0),vault,select_account=choose)
    results=[]; adapter.fill(results.append)
    script,_,callback=page.calls[-1]
    nonce=json.loads(script.rsplit(')(',1)[1][:-1])
    callback(json.dumps({'ok':True,'nonce':nonce,'origin':'https://example.com','action':'https://example.com/login'}))
    if case=='fill':
        assert len(uses)==1
        page.calls[-1][2]('{"ok":true}')
        assert results==['dispatched']
        with store.connect() as db:
            rows=db.execute('SELECT binding_sha256,consumed FROM browser_action_authorizations').fetchall()
            assert len(rows)==1 and rows[0]['consumed']==1
        assert requests[0]['action']=='login'
    else:
        assert not uses and results==['rejected']
    assert 'synthetic-password' not in str(results)
    adapter.close()
