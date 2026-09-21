"""Input gateway: one immutable TurnEnvelope per submitted turn.

The gateway is the single place where UI state (prompt, checked files,
model, permission mode) becomes a frozen envelope. Understanding, planning
and recovery reference the envelope hash; any drift in files, session,
account or permission mode fails verification instead of silently reusing a
stale understanding.
"""
from __future__ import annotations

from uuid import uuid4

from ..agent_contracts import EvidenceRef, UnderstandingRequest
from .turn_context import TurnEnvelope
from .turn_scope_policy import resolve_scope


class InputGateway:
    def __init__(self, store, permission_mode):
        if not callable(permission_mode):
            raise TypeError('Permission mode must be a provider callable')
        self.store = store
        self._permission_mode = permission_mode

    def create(self, session_id, raw_text, *, selected_ids, model_id,
               newly_attached_ids=(), browser_page_identity=None, clock=None) -> TurnEnvelope:
        session = self.store.session(session_id)
        files = self.store.files(session['project'])
        state_model = model_id if isinstance(model_id, str) and model_id.strip() else 'pending'
        return resolve_scope(
            owner=self.store.owner, project_id=session['project'], session_id=session_id,
            raw_user_text=raw_text, selected_ids=list(selected_ids), available_files=files,
            active_model_id=state_model, permission_mode=self._permission_mode(),
            newly_attached_ids=tuple(newly_attached_ids),
            browser_page_identity=browser_page_identity, clock=clock,
        )

    def verify(self, envelope) -> None:
        """Re-check that the frozen scope still matches live state."""
        envelope = TurnEnvelope.model_validate(envelope.model_dump()
                                               if isinstance(envelope, TurnEnvelope) else envelope)
        if envelope.owner != self.store.owner:
            raise PermissionError('本轮信封属于其他账号')
        session = self.store.session(envelope.session_id)
        if session['project'] != envelope.project_id:
            raise PermissionError('本轮信封的会话已变化')
        if envelope.permission_mode != self._permission_mode():
            raise PermissionError('权限模式已变化，本轮理解结果失效')
        available = {item['id']: item for item in self.store.files(envelope.project_id)}
        for item in envelope.selected_attachment_versions:
            record = available.get(item.id)
            if record is None or record['name'] != item.name or record['sha256'] != item.sha256:
                raise PermissionError('本轮文件范围已变化，请重新确认后提交')

    def understanding_request(self, envelope, *, skills, context, request_id=None) -> UnderstandingRequest:
        envelope = TurnEnvelope.model_validate(envelope.model_dump())
        return UnderstandingRequest(
            request_id=request_id or uuid4().hex,
            model_id=envelope.active_model_id,
            message_id=envelope.message_id,
            prompt=envelope.raw_user_text,
            files=[EvidenceRef(id=item.id, name=item.name, sha256=item.sha256)
                   for item in envelope.selected_attachment_versions],
            skills=list(skills),
            context=list(context),
        )
