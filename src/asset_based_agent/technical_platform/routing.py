"""Cancellable client intent-planning worker, independent of business execution."""
import threading
from uuid import uuid4

from PySide6.QtCore import QThread

from ..report_review_app.services.remote_auth_service import (
    BILLING_RECONCILIATION_MESSAGE,
    BillingReconciliationRequired,
    ServerCapabilityUnavailable,
)
from ..report_review_app.services.task_cancellation import (
    TaskCancelled,
    cancellable_call,
)


class RoutingWorker(QThread):
    def __init__(self, client, model_id, prompt, parent=None, candidates=None):
        super().__init__(parent)
        self.cancel = threading.Event()
        self.plan = None
        self.error = None
        self.client, self.model_id, self.prompt = client, model_id, prompt
        self.candidates = candidates or []

    def run(self):
        try:
            payload = {
                'request_id': uuid4().hex, 'model_id': self.model_id, 'prompt': self.prompt,
                'candidates': self.candidates}
            cancellable = getattr(self.client, 'route_skill_cancellable', None)
            call = (lambda: cancellable(payload, self.cancel)) if callable(cancellable) else (
                lambda: self.client.route_skill(payload))
            self.plan = cancellable_call(call, self.cancel)
        except TaskCancelled:
            self.error = '任务判断已取消，未启动业务执行。'
        except BillingReconciliationRequired:
            self.error = BILLING_RECONCILIATION_MESSAGE
        except ServerCapabilityUnavailable:
            self.error = '服务端任务接口不可用，请联系管理员核对部署版本和网关配置；未启动业务执行。'
        except Exception:  # noqa: BLE001 - UI boundary must not expose transport secrets
            self.error = '无法完成任务判断，请检查网络及服务端版本；未启动审核或文件生成。'


class UnderstandingWorker(QThread):
    def __init__(self, client, pending, parent=None):
        super().__init__(parent)
        self.client, self.pending = client, pending
        self.cancel = threading.Event()
        self.plan = None
        self.proposal = None
        self.error = None

    def run(self):
        try:
            self.plan = cancellable_call(
                lambda: self.client.understand_task(self.pending.request.model_dump(), cancel=self.cancel),
                self.cancel,
            )
            from ..agent_contracts import (
                PlanningRequest,
                PlanProposal,
                TaskUnderstanding,
                validate_proposal,
            )
            from .understanding_policy import assess_understanding
            result = assess_understanding(self.pending.request, TaskUnderstanding.model_validate(self.plan))
            self.plan = result.model_dump()
            if result.next_action == 'plan' and (len(result.skill_ids) > 1 or result.references):
                request = PlanningRequest(request=self.pending.request, understanding=result)
                proposal = cancellable_call(
                    lambda: self.client.propose_plan(request.model_dump(), cancel=self.cancel), self.cancel)
                if self.cancel.is_set():
                    raise TaskCancelled()
                self.proposal = validate_proposal(request, PlanProposal.model_validate(proposal)).model_dump()
        except TaskCancelled:
            self.error = '任务理解已取消，未启动业务执行。'
        except BillingReconciliationRequired:
            self.error = BILLING_RECONCILIATION_MESSAGE
        except ServerCapabilityUnavailable:
            self.error = '服务端缺少兼容的任务理解接口，请联系管理员升级；未执行业务。'
        except Exception:  # noqa: BLE001 - secrets never reach the conversation
            self.error = '任务理解未完成，请检查连接及服务端状态；未启动业务执行。'
