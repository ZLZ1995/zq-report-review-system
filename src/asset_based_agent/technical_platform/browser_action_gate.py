"""Native bridge from observed actions to durable, one-use task consent.

The resolver and confirmation callback belong to the host, never the webpage or
model. This adapter does not itself grant a task access to a browser tab.
"""
import json
from hashlib import sha256

from .browser_action_request import BrowserActionRequest


class BrowserActionGate:
    def __init__(self, service, leases, *, resolve, confirm):
        self.service, self.leases = service, leases
        self.resolve, self.confirm = resolve, confirm

    def click(self, lease, observation, control):
        return self._allow(lease, observation, control, 'click', '')

    def download(self, lease, observation, control):
        return self._allow(lease, observation, control, 'download', '')

    def scroll(self, lease, observation, direction):
        from ..browser_contracts import Control
        if direction not in {'up', 'down'}:
            return False
        return self._allow(lease, observation,
            Control(id='1', kind='button', text='当前页面视口', disabled=False), 'scroll', direction)

    def edit(self, lease, observation, control, operation, value):
        if operation not in {'fill', 'select'}:
            return False
        return self._allow(lease, observation, control, operation, value)

    def _request(self, lease, observation, control, operation, value):
        if not self.leases.valid(lease):
            raise PermissionError('Inactive browser lease')
        scope = self.resolve(lease)
        if not isinstance(scope, BrowserActionRequest):
            raise PermissionError('Missing native execution scope')
        scope = BrowserActionRequest.model_validate(scope.model_dump())
        if scope.environment != self.leases.session.environment:
            raise PermissionError('Browser environment mismatch')
        identity, binding = scope.identity, lease.binding
        if ((identity.owner, identity.project_id, identity.session_id, identity.task_id)
                != (binding.owner, binding.project_id, binding.session_id, binding.task_id)):
            raise PermissionError('Browser execution scope mismatch')
        payload = json.dumps({'observation': observation.model_dump(),
                              'control': control.model_dump(), 'value': value},
                             sort_keys=True, ensure_ascii=False, allow_nan=False)
        return BrowserActionRequest(
            identity=identity, step_id=scope.step_id, revision=scope.revision,
            claim_token=scope.claim_token, environment=scope.environment,
            tab_id=lease.tab_id, page_version=observation.page_version,
            origin=observation.origin, action=operation,
            target=sha256(observation.nonce.encode('utf-8')).hexdigest()+':'+control.id,
            payload_sha256=sha256(payload.encode('utf-8')).hexdigest())

    def _allow(self, lease, observation, control, operation, value):
        try:
            request = self._request(lease, observation, control, operation, value)
            self.service.verify(request.identity.task_id)
            if self.confirm(request, control, value) is not True:
                return False
            # A modal confirmation can process cancellation, takeover or a new
            # execution claim. Rebuild from live native state before issuing.
            if self._request(lease, observation, control, operation, value) != request:
                return False
            receipt = self.service.authorize_browser_action(request, confirmed=True)
            self.service.consume_browser_action(receipt, request)
            return True
        except (ValueError, TypeError, AttributeError, OSError, RuntimeError):
            return False
