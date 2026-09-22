"""K07: actionable error classification + secret-free diagnostics.

Every failure layer must surface a distinct, actionable message; unknown
errors must never masquerade as network failures; understanding-stage
failures must state that the Skill never started; 422/409/5xx keep distinct
safe codes; diagnostics log stage/class/code/ids and scrub secrets.
"""
import json
import logging
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))

import httpx
from openpyxl import Workbook

from asset_based_agent.report_review_app.services.remote_auth_service import (
    BILLING_RECONCILIATION_MESSAGE,
    BillingReconciliationRequired,
    InsufficientBalance,
    MemoryCredentialStore,
    NetworkUnavailable,
    RemoteAuthenticationError,
    RemoteSessionClient,
    ServerCapabilityUnavailable,
    SessionRevoked,
)
from asset_based_agent.technical_platform.agent_controller import AgentController
from asset_based_agent.technical_platform.routing import UnderstandingWorker
from asset_based_agent.technical_platform.skills import digest
from asset_based_agent.technical_platform.store import PlatformStore


class ErrorClassificationTest(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.store = PlatformStore(self.dir / 'state.db', 'test')
        self.project = self.store.create_project('p')
        self.session = self.store.create_session(self.project)
        source = self.dir / 'bs.xlsx'
        wb = Workbook()
        wb.active['A1'] = 'PRC-资产负债表'
        wb.save(source)
        self.file_id = self.store.add_file(self.project, source, digest(source))
        self.controller = AgentController(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def run_worker(self, exc):
        pending = self.controller.prepare(self.session, '生成评估明细表', model_id='m',
                                          selected_ids=[self.file_id])

        class Client:
            def understand_task(self, payload, *, cancel=None):
                raise exc

        worker = UnderstandingWorker(Client(), pending)
        worker.run()
        return worker, pending

    def test_network_unavailable(self):
        worker, _ = self.run_worker(NetworkUnavailable('无法连接审核服务，请检查网络。'))
        self.assertIn('网络', worker.error)
        self.assertIn('Skill尚未启动', worker.error)

    def test_session_revoked(self):
        worker, _ = self.run_worker(SessionRevoked('当前会话已失效。'))
        self.assertIn('登录', worker.error)
        self.assertNotIn('网络', worker.error)
        self.assertIn('Skill尚未启动', worker.error)

    def test_insufficient_balance(self):
        worker, _ = self.run_worker(InsufficientBalance('余额不足，无法开始本轮审核。'))
        self.assertIn('余额不足', worker.error)
        self.assertNotIn('网络', worker.error)

    def test_billing_reconciliation(self):
        worker, _ = self.run_worker(BillingReconciliationRequired('x'))
        self.assertEqual(BILLING_RECONCILIATION_MESSAGE, worker.error)

    def test_server_capability(self):
        worker, _ = self.run_worker(ServerCapabilityUnavailable('服务端缺少接口'))
        self.assertIn('升级', worker.error)
        self.assertNotIn('网络', worker.error)

    def test_request_schema_failure(self):
        from asset_based_agent.report_review_app.services.remote_auth_service import (
            RequestSchemaError,
        )
        worker, _ = self.run_worker(RequestSchemaError('本轮理解请求未通过本地Schema校验，未发送。'))
        self.assertIn('本地', worker.error)
        self.assertIn('校验', worker.error)
        self.assertIn('Skill尚未启动', worker.error)
        self.assertNotIn('网络', worker.error)

    def test_response_schema_failure(self):
        from asset_based_agent.report_review_app.services.remote_auth_service import (
            ResponseSchemaError,
        )
        worker, _ = self.run_worker(
            ResponseSchemaError('服务端任务理解响应未通过Schema校验，未开始业务执行。'))
        self.assertIn('校验', worker.error)
        self.assertIn('Skill尚未启动', worker.error)
        self.assertNotIn('连接', worker.error)
        self.assertNotIn('网络', worker.error)

    def test_safe_server_message_is_surfaced(self):
        worker, _ = self.run_worker(
            RemoteAuthenticationError('任务理解结果未通过校验，未开始执行。'))
        self.assertIn('校验', worker.error)
        self.assertIn('Skill尚未启动', worker.error)
        self.assertNotIn('连接', worker.error)

    def test_unknown_error_is_not_a_network_message(self):
        worker, _ = self.run_worker(RuntimeError('boom'))
        self.assertIn('未分类', worker.error)
        self.assertNotIn('连接', worker.error)
        self.assertNotIn('网络', worker.error)
        self.assertIn('Skill尚未启动', worker.error)

    def test_diagnostics_log_capture_and_secret_scrubbing(self):
        logger = logging.getLogger('asset_based_agent.diagnostics')
        records = []

        class Handler(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Handler()
        logger.addHandler(handler)
        try:
            _, pending = self.run_worker(RuntimeError('boom'))
            secret = 'Bearer abcdef123SECRET token=xyz789'
            self.run_worker(RemoteAuthenticationError(f'远程服务请求失败。{secret}'))
        finally:
            logger.removeHandler(handler)
        self.assertTrue(records, 'worker failures must be logged')
        first = records[0]
        self.assertIn('understand', first)
        self.assertIn('RuntimeError', first)
        self.assertIn(pending.task_id, first)
        self.assertIn(str(pending.revision), first)
        self.assertIn(pending.request.request_id, first)
        blob = '\n'.join(records)
        self.assertNotIn('abcdef123SECRET', blob)
        self.assertNotIn('xyz789', blob)


class HttpStatusCodeTest(unittest.TestCase):
    """422/409/5xx keep distinct safe codes through the remote client."""

    def make_client(self, status):
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200, json={
                    'schema_version': 1, 'protocol_version': 1,
                    'capabilities': {'task_understanding': 1, 'material_evidence': 1}})
            return httpx.Response(status, json={
                'error': {'code': 'http_error', 'message': f'服务端错误 {status}'}})

        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(),
                                     http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        client.access_token = 'synthetic'
        return client

    def check(self, status):
        client = self.make_client(status)
        payload = {'request_id': 'r', 'model_id': 'm', 'message_id': 'msg', 'prompt': '做表'}
        with self.assertRaises(RemoteAuthenticationError) as ctx:
            client.understand_task(payload)
        return ctx.exception

    def test_422_keeps_distinct_code(self):
        exc = self.check(422)
        self.assertEqual('http_422', exc.error_code)

    def test_409_keeps_distinct_code(self):
        exc = self.check(409)
        self.assertEqual('http_409', exc.error_code)

    def test_500_keeps_distinct_code(self):
        exc = self.check(500)
        self.assertEqual('http_500', exc.error_code)

    def test_bad_reply_raises_response_schema_error(self):
        from asset_based_agent.report_review_app.services.remote_auth_service import (
            ResponseSchemaError,
        )

        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200, json={
                    'schema_version': 1, 'protocol_version': 1,
                    'capabilities': {'task_understanding': 1}})
            return httpx.Response(200, json={'not': 'an understanding'})

        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(),
                                     http_client=httpx.Client(transport=httpx.MockTransport(handler)))
        client.access_token = 'synthetic'
        with self.assertRaises(ResponseSchemaError):
            client.understand_task({'request_id': 'r', 'model_id': 'm',
                                    'message_id': 'msg', 'prompt': '做表'})

    def test_bad_request_raises_request_schema_error(self):
        from asset_based_agent.report_review_app.services.remote_auth_service import (
            RequestSchemaError,
        )
        client = RemoteSessionClient('https://review.example/api/v1', client_instance_id='test',
                                     credential_store=MemoryCredentialStore(),
                                     http_client=httpx.Client(transport=httpx.MockTransport(
                                         lambda request: httpx.Response(500))))
        client.access_token = 'synthetic'
        with self.assertRaises(RequestSchemaError):
            client.understand_task({'bogus': True})


if __name__ == '__main__':
    unittest.main()
