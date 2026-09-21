"""Turn router: formal boundary between non-execution messages and the business chain.

Every submitted turn first passes a light stage-1 understanding (user text,
conversation context, attachment identities only — never MaterialEvidence, file
content or full Skill instructions). The model judges intent; local policy binds
the result to the frozen request. Only execution outcomes enter
`AgentController.prepare` (which then loads full material evidence); consult
answers never create a task, never touch a pending clarification and never
reserve billing. A narrow deterministic social fast path handles exact
greetings/thanks as a latency optimization — every other text is judged by the
structured model, never by keyword lists.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from ..agent_contracts import (
    EvidenceRef,
    SkillCandidate,
    TaskUnderstanding,
    UnderstandingRequest,
    validate_understanding,
)
from .branch_understanding import branch_messages
from .capability_registry import planning_candidates
from .conversation_state import ConversationState
from .turn_normalizer import normalize_text

# Deterministic social fast path: exact normalized matches only. Anything that
# carries an action, a file mention or extra words falls through to the model.
_SOCIAL_REPLIES = {
    '你好': '你好！我是 ZQ 技术平台助手。可以帮你审核报告、生成评估明细表，也可以直接问我功能或业务问题。',
    '您好': '您好！我是 ZQ 技术平台助手。可以帮你审核报告、生成评估明细表，也可以直接问我功能或业务问题。',
    '早上好': '早上好！有什么可以帮你的？',
    '晚上好': '晚上好！有什么可以帮你的？',
    '谢谢': '不客气！有需要随时告诉我。',
    '谢谢你': '不客气！有需要随时告诉我。',
    '谢谢啦': '不客气！有需要随时告诉我。',
    '再见': '再见！有需要随时回来找我。',
    '你是谁': '我是 ZQ 技术平台助手，可以帮你审核评估报告、生成评估明细表、查询项目状态，也可以回答业务问题。',
}
_STAGE1_DESCRIPTION_LIMIT = 240


def _call_with_request_id(call, request_id):
    """Attach the understanding request id to any failure for log correlation."""
    try:
        return call()
    except Exception as exc:
        try:
            exc.request_id = request_id
        except Exception:  # noqa: BLE001, S110 - some C exceptions reject attributes
            pass
        raise


@dataclass(frozen=True)
class TurnOutcome:
    kind: Literal['answer', 'execution', 'cancel', 'refuse']
    reply: str = ''
    pending: object = None  # PendingUnderstanding when kind == 'execution'


def _stage1_skills(candidates, *, browser_enabled) -> list[SkillCandidate]:
    """Identities, names and trimmed summaries only — never full instructions."""
    skills = [*planning_candidates(include_browser=browser_enabled), *candidates]
    trimmed = []
    for skill in skills:
        skill = SkillCandidate.model_validate(
            skill.model_dump() if isinstance(skill, SkillCandidate) else skill)
        trimmed.append(skill.model_copy(
            update={'description': skill.description[:_STAGE1_DESCRIPTION_LIMIT]}))
    return trimmed


class TurnRouter:
    def __init__(self, store, client):
        self.store = store
        self.client = client
        self.state = ConversationState(store)

    def submit(self, session_id, prompt, *, model_id, selected_ids, candidates=(),
               browser_enabled=False, envelope=None, cancel=None) -> TurnOutcome:
        from ..report_review_app.services.task_cancellation import (
            TaskCancelled,
            cancellable_call,
        )
        from .agent_controller import AgentController
        if cancel is not None and cancel.is_set():
            raise TaskCancelled()
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('本轮内容为空')
        prompt = prompt.strip()
        session = self.store.session(session_id)
        available = {f['id']: f for f in self.store.files(session['project'])}
        if len(set(selected_ids)) != len(selected_ids) or any(i not in available for i in selected_ids):
            raise PermissionError('本轮文件范围不属于当前项目或已变化')
        files = [available[i] for i in selected_ids]

        # 1) Deterministic social fast path (exact match only; latency optimization).
        social = _SOCIAL_REPLIES.get(normalize_text(prompt).replace(' ', ''))
        if social is not None:
            self.store.append(session_id, 'user', prompt)
            self.store.append(session_id, 'assistant', social)
            return TurnOutcome(kind='answer', reply=social)

        # 2) Stage-1 light intent analysis: text + context + attachment identities.
        state = self.state.read(session_id)
        inherited = branch_messages(self.store, session_id)
        context = inherited
        if state['question'] and not state['cancelled']:
            question = state['question']
            context = list(question.get('context', [])) + [
                {'id': question['id'], 'role': 'assistant', 'text': question['text']}]
        request = UnderstandingRequest(
            request_id=uuid4().hex, model_id=model_id, message_id=uuid4().hex,
            prompt=prompt,
            files=[EvidenceRef(id=f['id'], name=f['name'], sha256=f['sha256']) for f in files],
            skills=_stage1_skills(candidates, browser_enabled=browser_enabled),
            context=context)
        payload = request.model_dump()
        raw = _call_with_request_id(
            lambda: (self.client.understand_task(payload) if cancel is None else
                     cancellable_call(lambda: self.client.understand_task(payload, cancel=cancel),
                                      cancel)),
            request.request_id)
        result = validate_understanding(request, TaskUnderstanding.model_validate(raw))

        # 3) Non-execution outcomes never create or disturb task state.
        if result.next_action == 'answer':
            from .platform_queries import platform_answer
            reply = platform_answer(self.store, session_id, prompt, client=self.client)
            audit = None
            if reply is None:
                reply, audit = self._file_qa_reply(
                    session, prompt, files, context, model_id, selected_ids,
                    fallback=result.reply, cancel=cancel)
            self.store.append(session_id, 'user', prompt)
            if audit:
                self.store.append(session_id, 'event', audit)
            self.store.append(session_id, 'assistant', reply)
            return TurnOutcome(kind='answer', reply=reply)
        if result.next_action in ('cancel', 'refuse'):
            reply = result.reply
            if result.next_action == 'cancel':
                current = self.state.read(session_id)
                if current['task_id'] and not current['cancelled']:
                    self.state.cancel(session_id, current['revision'])
                    reply = reply or '已取消当前任务。'
            self.store.append(session_id, 'user', prompt)
            self.store.append(session_id, 'assistant', reply)
            return TurnOutcome(kind=result.next_action, reply=reply)

        # 4) Execution outcomes enter the full chain, which loads material evidence.
        # 待澄清期间的执行裁决：恢复原任务与原信封约束（prepare 的 resume 路径），
        # 并显式告知用户——继续不是静默拼接，用户可随时说“取消”另起新任务。
        current = self.state.read(session_id)
        resuming = bool(current['question'] and not current['cancelled'])
        controller = AgentController(self.store)
        pending = controller.prepare(
            session_id, prompt, model_id=model_id, selected_ids=selected_ids,
            candidates=candidates, browser_enabled=browser_enabled, envelope=envelope)
        if resuming:
            self.store.append(session_id, 'assistant',
                '正在继续上一个等待补充信息的任务；如需另起新任务，请先发送“取消”结束当前任务。')
        return TurnOutcome(kind='execution', reply=result.reply, pending=pending)

    def _file_qa_reply(self, session, prompt, files, context, model_id, selected_ids,
                       *, fallback, cancel):
        """文件只读问答：仅对本轮明确指向的文件取可见摘要，请模型据摘要回答。

        返回 (reply, audit)；未指向任何文件时返回 (fallback, None)。
        """
        from ..report_review_app.services.task_cancellation import cancellable_call
        from .platform_queries import pointed_file_ids, visible_summaries
        pointed = pointed_file_ids(self.store, session['project'], prompt, selected_ids)
        summaries = visible_summaries(self.store, session['project'], pointed)
        if not summaries:
            return fallback, None
        digest = '\n\n'.join(
            f'【{item["name"]} 可见内容摘要】\n{item["summary"]}' for item in summaries)
        by_id = {f['id']: f for f in files}
        refs = [EvidenceRef(id=by_id[i]['id'], name=by_id[i]['name'], sha256=by_id[i]['sha256'])
                for i in pointed if i in by_id]
        request = UnderstandingRequest(
            request_id=uuid4().hex, model_id=model_id, message_id=uuid4().hex,
            prompt=(prompt + '\n\n以下是用户本轮明确指向文件的只读可见摘要。'
                    '仅根据摘要与常识回答；摘要中没有的信息请明确说明“摘要中看不到”，'
                    '不得编造：\n' + digest),
            files=refs, skills=[], context=context)
        payload = request.model_dump()
        raw = _call_with_request_id(
            lambda: (self.client.understand_task(payload) if cancel is None else
                     cancellable_call(lambda: self.client.understand_task(payload, cancel=cancel),
                                      cancel)),
            request.request_id)
        result = validate_understanding(request, TaskUnderstanding.model_validate(raw))
        names = '、'.join(item['name'] for item in summaries)
        audit = f'文件只读问答：仅读取本轮明确指向的 {names}（可见摘要，未修改原件）。'
        if result.next_action == 'answer' and result.reply:
            return result.reply, audit
        return fallback, audit
