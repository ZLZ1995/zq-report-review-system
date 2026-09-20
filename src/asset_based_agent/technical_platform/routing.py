"""Cancellable client intent-planning worker, independent of business execution."""
import threading
from uuid import uuid4

from PySide6.QtCore import QThread

from ..report_review_app.services.remote_auth_service import (
    BILLING_RECONCILIATION_MESSAGE,
    BillingReconciliationRequired,
    InsufficientBalance,
    NetworkUnavailable,
    RemoteAuthenticationError,
    RequestSchemaError,
    ResponseSchemaError,
    ServerCapabilityUnavailable,
    SessionRevoked,
)
from .diagnostics import log_worker_failure
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
        except BillingReconciliationRequired as exc:
            self.error = BILLING_RECONCILIATION_MESSAGE
            log_worker_failure('route', exc)
        except InsufficientBalance as exc:
            self.error = str(exc).rstrip('。') + '；未启动业务执行。'
            log_worker_failure('route', exc)
        except NetworkUnavailable as exc:
            self.error = '无法连接服务端，请检查网络后重试；未启动业务执行。'
            log_worker_failure('route', exc)
        except SessionRevoked as exc:
            self.error = '登录会话已失效，请重新登录后再试；未启动业务执行。'
            log_worker_failure('route', exc)
        except ServerCapabilityUnavailable as exc:
            self.error = '服务端任务接口不可用，请联系管理员核对部署版本和网关配置；未启动业务执行。'
            log_worker_failure('route', exc)
        except (RequestSchemaError, ResponseSchemaError) as exc:
            self.error = str(exc).rstrip('。') + '；未启动业务执行。'
            log_worker_failure('route', exc)
        except RemoteAuthenticationError as exc:
            self.error = str(exc).rstrip('。') + '；未启动业务执行。'
            log_worker_failure('route', exc)
        except (ValueError, PermissionError) as exc:
            self.error = '任务判断请求或结果未通过本地校验；未启动业务执行。'
            log_worker_failure('route', exc)
        except Exception as exc:  # noqa: BLE001 - UI boundary must not expose transport secrets
            self.error = '任务判断未完成（未分类内部错误）；未启动业务执行。'
            log_worker_failure('route', exc)


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
        except BillingReconciliationRequired as exc:
            self.error = BILLING_RECONCILIATION_MESSAGE
            self._log(exc)
        except InsufficientBalance as exc:
            self.error = str(exc).rstrip('。') + '；Skill尚未启动，未创建业务任务。'
            self._log(exc)
        except NetworkUnavailable as exc:
            self.error = '无法连接服务端，请检查网络后重试；Skill尚未启动，未创建业务任务。'
            self._log(exc)
        except SessionRevoked as exc:
            self.error = '登录会话已失效，请重新登录后再试；Skill尚未启动。'
            self._log(exc)
        except ServerCapabilityUnavailable as exc:
            self.error = '服务端缺少兼容的任务理解接口，请联系管理员升级；Skill尚未启动。'
            self._log(exc)
        except (RequestSchemaError, ResponseSchemaError) as exc:
            self.error = str(exc).rstrip('。') + '；Skill尚未启动，未创建业务任务。'
            self._log(exc)
        except RemoteAuthenticationError as exc:
            self.error = str(exc).rstrip('。') + '；Skill尚未启动，未创建业务任务。'
            self._log(exc)
        except (ValueError, PermissionError) as exc:
            self.error = '理解请求或结果未通过本地校验；Skill尚未启动，未创建业务任务。'
            self._log(exc)
        except Exception as exc:  # noqa: BLE001 - secrets never reach the conversation
            self.error = '任务理解未完成（未分类内部错误）；Skill尚未启动，未创建业务任务。'
            self._log(exc)

    def _log(self, exc):
        pending = self.pending
        request = getattr(pending, 'request', None)
        log_worker_failure('understand', exc,
                           request_id=getattr(request, 'request_id', None),
                           task_id=getattr(pending, 'task_id', None),
                           revision=getattr(pending, 'revision', None))
