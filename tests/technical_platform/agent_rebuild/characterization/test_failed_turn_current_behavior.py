"""S01 现状冻结：失败 Turn。

已知缺陷（xfail）：SES-03/SES-04 失败轮次不落库、无 request_id 与错误分类，
用户消息凭空消失，无法对账。
"""
import pytest
from conftest import failing_consult_worker
from test_consultation_routing import make_store


@pytest.mark.xfail(reason='SES-04：远程咨询失败只设置内存 error，会话不留任何痕迹', strict=True)
def test_failed_consult_persists_user_and_assistant_failure(tmp_path):
    store, _project, session = make_store(tmp_path)
    _spy, worker = failing_consult_worker(store, session, '你能帮我做什么')
    assert worker.error, '失败必须被分类记录'
    roles = [m['role'] for m in store.messages(session)]
    assert roles == ['user', 'assistant'], '失败轮次必须留下用户消息和助手失败回复'
    assert store.messages(session)[1]['text'].strip()


@pytest.mark.xfail(reason='SES-04：失败轮次没有持久化 request_id/错误分类，无法追踪与对账', strict=True)
def test_failed_consult_persists_request_id_reference(tmp_path):
    store, _project, session = make_store(tmp_path)
    spy, _worker = failing_consult_worker(store, session, '你能帮我做什么')
    failure = store.messages(session)[1]['text']
    request_id = spy.understand_calls[0]['request_id']
    assert request_id[:8] in failure, '用户可见失败必须带诊断/request 编号'
