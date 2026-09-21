"""Qt-free message understanding lifecycle. Never grants execution authority."""
from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from ..agent_contracts import (
    EvidenceRef,
    TaskUnderstanding,
    UnderstandingRequest,
)
from . import material_summary
from .branch_understanding import PREFIX, branch_messages
from .capability_registry import planning_candidates
from .conversation_state import ConversationState
from .understanding_policy import assess_understanding


def _evidence_ref(record):
    """Attach a bounded local summary for workbooks; metadata only otherwise."""
    fields = {key: record[key] for key in ('id', 'name', 'sha256')}
    from pathlib import Path
    if Path(record['name']).suffix.lower() in material_summary.SUPPORTED_EXTENSIONS:
        summary = material_summary.summarize_file(
            record['path'], record['id'], record['name'])
        fields['evidence'] = {key: value for key, value in summary.items()
                              if key not in ('artifact_id', 'name')}
    return EvidenceRef.model_validate(fields)


class ClarificationContextLimit(ValueError):
    """Cannot safely continue without discarding part of the user's requirements."""


@dataclass(frozen=True)
class PendingUnderstanding:
    owner: str
    project_id: str
    session_id: str
    task_id: str
    revision: int
    request: UnderstandingRequest
    files: tuple[dict, ...]
    envelope_hash: str | None = None


class AgentController:
    def __init__(self, store):
        from .project_catalog import ProjectCatalog
        if isinstance(store, ProjectCatalog):
            if store.active is None:
                raise ValueError('请先打开项目')
            store = store.active
        self.store = store
        self.state = ConversationState(store)

    def prepare(self, session_id, prompt, *, model_id, selected_ids, candidates=(), browser_enabled=False, envelope=None):
        from ..agent_contracts import SkillCandidate
        envelope_digest = None
        if envelope is not None:
            from .turn_context import TurnEnvelope, envelope_hash
            envelope = TurnEnvelope.model_validate(envelope.model_dump())
            if (envelope.raw_user_text != prompt or envelope.active_model_id != model_id
                    or set(selected_ids) != {item.id for item in envelope.selected_attachment_versions}
                    or envelope.session_id != session_id):
                raise ValueError('本轮信封与提交内容不一致')
            envelope_digest = envelope_hash(envelope)
        candidates = [SkillCandidate.model_validate(item) for item in candidates]
        if any(item.adapter == 'browser.task' or item.id == 'browser.task' for item in candidates):
            raise PermissionError('外部Skill不能声明或启用原生浏览器能力')
        session = self.store.session(session_id)
        available = {f['id']: f for f in self.store.files(session['project'])}
        if len(set(selected_ids)) != len(selected_ids) or any(i not in available for i in selected_ids):
            raise PermissionError('本轮文件范围不属于当前项目或已变化')
        files = [available[i] for i in selected_ids]
        state = self.state.read(session_id)
        inherited = branch_messages(self.store, session_id)
        context = inherited
        resuming = bool(state['question'] and not state['cancelled'])
        if resuming:
            question = state['question']
            context = list(question.get('context', [])) + [
                {'id': question['id'], 'role': 'assistant', 'text': question['text']}]
            if [m for m in context if m['id'].startswith(PREFIX)] != inherited:
                raise ValueError('分支参考已变化，请重新确认本轮要求')
        request = UnderstandingRequest(
            request_id=uuid4().hex, model_id=model_id, message_id=uuid4().hex, prompt=prompt,
            files=[_evidence_ref(f) for f in files],
            skills=planning_candidates(include_browser=browser_enabled) + list(candidates), context=context,
        )
        state = (self.state.resume(session_id, state['revision']) if resuming else
                 self.state.start(session_id, expected_revision=state['revision']))
        self.store.append(session_id, 'user', prompt)
        return PendingUnderstanding(self.store.owner, session['project'], session_id,
                                    state['task_id'], state['revision'], request, tuple(deepcopy(files)),
                                    envelope_digest)

    @staticmethod
    def _validate_next_exchange(pending, messages):
        UnderstandingRequest.model_validate({**pending.request.model_dump(),
            'message_id': uuid4().hex, 'prompt': '请补充本轮要求',
            'context': messages})

    def _current(self, pending):
        if pending.owner != self.store.owner:
            raise PermissionError('理解结果账号不匹配')
        session = self.store.session(pending.session_id)
        state = self.state.read(pending.session_id)
        if (session['project'] != pending.project_id or state['cancelled'] or
                state['task_id'] != pending.task_id or state['revision'] != pending.revision):
            raise ValueError('本轮理解已失效，不会执行迟到的结果')
        return state

    def cancel(self, pending):
        self._current(pending)
        self.state.cancel(pending.session_id, pending.revision)

    def complete(self, pending, payload):
        self._current(pending)
        expected = [m.model_dump() for m in pending.request.context if m.id.startswith(PREFIX)]
        if branch_messages(self.store, pending.session_id) != expected:
            raise ValueError('理解期间分支参考已变化，不会采用迟到结果')
        result = assess_understanding(pending.request, TaskUnderstanding.model_validate(payload))
        available = {f['id']: f for f in self.store.files(pending.project_id)}
        if any(available.get(f['id']) != f for f in pending.files):
            raise ValueError('理解期间文件记录发生变化，请重新确认范围')
        if result.next_action == 'ask':
            context = [m.model_dump() for m in pending.request.context] + [
                {'id': pending.request.message_id, 'role': 'user', 'text': pending.request.prompt}]
            question_message = {'id': uuid4().hex, 'role': 'assistant', 'text': result.reply}
            # Validate the NEXT exchange before persisting the question. Never
            # truncate a restriction or leave an unresumable oversized question.
            try:
                self._validate_next_exchange(pending, context + [question_message])
            except ValueError:
                # 先压缩（摘要标记非原始证据、分支参考不动），仍超界才明确拒绝。
                from .context_assembly import compact_clarification_context
                compacted = compact_clarification_context(context)
                try:
                    self._validate_next_exchange(pending, compacted + [question_message])
                except ValueError as exc:
                    raise ClarificationContextLimit('澄清上下文已达上限，未丢弃任何限制；请新建会话并完整描述目标、资料范围和限制。') from exc
                context = compacted
            self.state.ask(pending.session_id, pending.revision, result.reply, context=context)
        else:
            # Close this understanding revision, not a running business task.
            # A plan remains merely a proposal; execution needs its own guards.
            self.state.cancel(pending.session_id, pending.revision)
        self.store.append(pending.session_id, 'assistant', result.reply)
        return result
