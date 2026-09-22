"""Stable agent error taxonomy.

每个错误都有稳定 code；禁止宽泛捕获后统一成“未分类内部错误”。
"""


class AgentError(Exception):
    code = 'agent.internal'

    def __init__(self, message='', *, detail=None):
        super().__init__(message)
        self.detail = detail


class InvalidRequest(AgentError):
    code = 'agent.invalid_request'


class ContextOverflow(AgentError):
    code = 'agent.context_overflow'


class OperationBusy(AgentError):
    code = 'agent.operation_busy'


class AgentCancelled(AgentError):
    code = 'agent.cancelled'


class AgentInternalError(AgentError):
    """未归类内部异常的安全收束码：不泄露路径、token、堆栈。"""

    code = 'agent.internal_error'


class ModelAuthFailed(AgentError):
    code = 'model.auth_failed'


class ModelBalanceInsufficient(AgentError):
    code = 'model.balance_insufficient'


class ModelTimeout(AgentError):
    code = 'model.timeout'


class ModelProtocolError(AgentError):
    code = 'model.protocol_error'


class ServerCapabilityUnavailable(AgentError):
    code = 'server.capability_missing'


class ModelBillingReconciliation(AgentError):
    code = 'model.billing_reconciliation'


class ToolInvalidArguments(AgentError):
    code = 'tool.invalid_arguments'


class ToolPermissionDenied(AgentError):
    code = 'tool.permission_denied'


class ToolFailed(AgentError):
    code = 'tool.failed'


class ToolUnknownOutcome(AgentError):
    code = 'tool.unknown_outcome'


class SessionStaleRevision(AgentError):
    code = 'session.stale_revision'


class SessionCorrupted(AgentError):
    code = 'session.corrupted'


class ResourceVersionChanged(AgentError):
    code = 'resource.version_changed'


class ResourceManifestInvalid(AgentError):
    code = 'resource.manifest_invalid'


class ResourceTampered(AgentError):
    code = 'resource.tampered'


class ResourceDisabled(AgentError):
    code = 'resource.disabled'


_CLASSES = (
    InvalidRequest, ContextOverflow, OperationBusy, AgentCancelled,
    AgentInternalError,
    ModelAuthFailed, ModelBalanceInsufficient, ModelTimeout, ModelProtocolError,
    ServerCapabilityUnavailable,
    ModelBillingReconciliation, ToolInvalidArguments, ToolPermissionDenied,
    ToolFailed, ToolUnknownOutcome, SessionStaleRevision, SessionCorrupted,
    ResourceVersionChanged, ResourceManifestInvalid, ResourceTampered,
    ResourceDisabled,
)

ERROR_CODES = frozenset(cls.code for cls in _CLASSES)
_BY_CODE = {cls.code: cls for cls in _CLASSES}


def error_class_for(code):
    return _BY_CODE[code]
