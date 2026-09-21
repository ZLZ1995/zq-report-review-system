from types import SimpleNamespace

import httpx
import pytest

from asset_based_agent.report_review_app.services import remote_auth_service as remote
from asset_based_agent.technical_platform.diagnostics import failure_message
from asset_based_agent.technical_platform.routing import UnderstandingWorker
from asset_based_agent.technical_platform.store import PlatformStore


def test_remote_unknown_billing_is_typed_and_does_not_echo_server_secrets():
    response = httpx.Response(409, json={'error': {
        'code': 'billing_reconciliation_required', 'message': 'secret-provider-key'}})
    with pytest.raises(remote.BillingReconciliationRequired) as caught:
        remote.RemoteSessionClient._raise_for_response(response)
    assert '费用待核对' in str(caught.value)
    assert 'secret' not in str(caught.value)


def test_understanding_worker_explains_billing_not_network():
    def understand(*args, **kwargs):
        raise remote.BillingReconciliationRequired('secret-token')
    pending = SimpleNamespace(request=SimpleNamespace(model_dump=dict))
    worker = UnderstandingWorker(SimpleNamespace(understand_task=understand), pending)
    worker.run()
    assert '费用待核对' in worker.error and '不要重复提交' in worker.error
    assert 'secret' not in worker.error and worker.plan is None


def test_persisted_task_failure_gives_billing_guidance(tmp_path):
    store = PlatformStore(tmp_path / 'db.sqlite', 'alice')
    session = store.create_session(store.create_project('one'))
    run = store.start_run(session, {'files': []})
    store.transition(run, 'failed', 'execution: BillingReconciliationRequired')
    message = failure_message(store, run)
    assert '费用待核对' in message and '联系管理员' in message
    assert '不要重复提交' in message
