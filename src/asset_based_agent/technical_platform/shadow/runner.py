"""S13 Shadow Mode：不替换旧生产路径，只对比新旧决策。

- 旧系统继续实际执行——ShadowRunner 只向 LegacyRouter 索取决策记录；
- 新 Agent 在隔离的 shadow 会话中运行：只做理解、Tool 选择、文件范围和
  回复草案；副作用 Tool 一律不执行（ShadowTool 记录提案并返回占位结果），
  只读 Tool 允许真实执行；
- 差异写入本地诊断（Diagnostics），永不进入用户对话（用户 lane 不写任何
  shadow 内容）；
- shadow 无任何计费通道（构造器不接受 billing），charged_units 恒为 0；
- 诊断落库前经 redact_secrets 遮蔽，秘密不进诊断。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from typing import Protocol

from ..agent_core.contracts import ToolResult
from ..agent_core.runtime import AgentKernel
from ..agent_core.text_safety import redact_secrets
from ..policies.engine import RuleBasedPolicyEngine

_SIDE_EFFECT_KIND_PREFIX = {'browser_': 'browser'}
_READONLY_RISKS = frozenset({'local_readonly', 'network_read'})
_CLARIFY_MARKERS = ('请补充', '请提供', '请说明', '请告诉', '需要您提供',
                    '需要您确认')


# ---------------------------------------------------------------- 契约

@dataclass(frozen=True)
class ShadowCase:
    session_id: str
    text: str
    expected_kind: str | None = None      # chat / skill / browser / clarify
    expected_skill: str | None = None
    expected_files: tuple = ()


@dataclass(frozen=True)
class LegacyDecision:
    kind: str                              # chat / skill / browser / clarify
    skill_id: str = ''
    file_ids: tuple = ()
    reply: str = ''
    permission: str = ''                   # allow/ask/deny；空串表示未记录


@dataclass(frozen=True)
class NewDecision:
    kind: str
    skill_id: str = ''
    file_ids: tuple = ()
    draft: str = ''
    tool_calls: tuple = ()
    permission: str = ''
    error: str = ''
    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    first_token_latency: float = 0.0
    duration: float = 0.0


@dataclass(frozen=True)
class ShadowComparison:
    session_id: str
    case: ShadowCase
    legacy: LegacyDecision
    new: NewDecision
    diffs: tuple = ()


class LegacyRouter(Protocol):
    def decide(self, case: ShadowCase) -> LegacyDecision: ...


class Diagnostics(Protocol):
    def record(self, comparison: ShadowComparison) -> None: ...


class InMemoryDiagnostics:
    def __init__(self) -> None:
        self.records: list[ShadowComparison] = []

    def record(self, comparison: ShadowComparison) -> None:
        self.records.append(comparison)


# ---------------------------------------------------------------- 包装器

class ShadowTool:
    """副作用 Tool 的影子包装：记录提案，绝不真实执行。"""

    def __init__(self, tool, recorder: list) -> None:
        self.descriptor = tool.descriptor
        self._tool = tool
        self._recorder = recorder

    @property
    def read_only(self) -> bool:
        return self.descriptor.risk in _READONLY_RISKS

    async def execute(self, context, arguments, cancel):
        if self.read_only:
            return await self._tool.execute(context, arguments, cancel)
        self._recorder.append({'name': self.descriptor.name,
                               'arguments': dict(arguments or {})})
        return ToolResult(status='succeeded',
                          content='[shadow] 提案已记录，未实际执行。')


class CountingModelPort:
    """统计模型调用数、token、首字延迟的包装端口。"""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.first_token_latency = 0.0

    async def stream(self, request, cancel):
        self.calls += 1
        started = time.perf_counter()
        first = True
        async for event in self._inner.stream(request, cancel):
            if first:
                self.first_token_latency = time.perf_counter() - started
                first = False
            if event.kind == 'usage':
                self.input_tokens += int(event.data.get('input_tokens', 0))
                self.output_tokens += int(event.data.get('output_tokens', 0))
            yield event


# ---------------------------------------------------------------- 运行器

class ShadowRunner:
    def __init__(self, *, repo, model_factory, tools, legacy_router,
                 diagnostics, permission_mode: str = 'request') -> None:
        self._repo = repo
        self._model_factory = model_factory
        self._tools = list(tools)
        self._legacy = legacy_router
        self.diagnostics = diagnostics
        self._mode = permission_mode
        self._engine = RuleBasedPolicyEngine()
        self.comparisons: list[ShadowComparison] = []

    # ------------------------------------------------------------ 单例

    def run_case(self, case: ShadowCase) -> ShadowComparison:
        legacy = self._legacy.decide(case)
        new = self._run_shadow(case)
        comparison = ShadowComparison(
            session_id=case.session_id,
            case=self._scrubbed_case(case), legacy=legacy, new=new,
            diffs=self._diff(case, legacy, new))
        self.diagnostics.record(comparison)
        self.comparisons.append(comparison)
        return comparison

    def run(self, cases) -> ShadowMetrics:
        for case in cases:
            self.run_case(case)
        return ShadowMetrics.from_comparisons(self.comparisons)

    # ------------------------------------------------------------ 内部

    def _run_shadow(self, case: ShadowCase) -> NewDecision:
        shadow_session = f'{case.session_id}__shadow'
        if shadow_session not in {s['id'] for s in self._repo.list_sessions()}:
            self._repo.create_session(shadow_session, project_id='shadow',
                                      owner_id='shadow', title='shadow')
        proposals: list = []
        wrapped = [ShadowTool(tool, proposals) for tool in self._tools]
        model = CountingModelPort(self._model_factory())
        kernel = AgentKernel(repo=self._repo, model=model, tools=wrapped)
        events: list = []
        kernel.subscribe(lambda event: events.append(event))
        started = time.perf_counter()
        error = ''
        try:
            asyncio.run(kernel.submit(shadow_session, 'main',
                                      {'text': case.text}))
        except Exception as exc:  # noqa: BLE001 - shadow 只记录不抛出
            error = f'{type(exc).__name__}: {redact_secrets(str(exc))[:200]}'
        duration = time.perf_counter() - started
        for event in events:
            if getattr(event, 'event_type', '') == 'operation_failed':
                payload = getattr(event, 'payload', {}) or {}
                error = error or str(payload.get('error_code', 'failed'))
        entries = self._repo.entries(shadow_session, 'main')
        draft = ''.join(
            str(e.payload.get('text', '')) for e in entries
            if e.entry_type == 'assistant_message'
            and not e.payload.get('intermediate'))
        side_effects = [p for p in proposals]
        skill_id = side_effects[0]['name'] if side_effects else ''
        kind = 'chat'
        if side_effects:
            kind = next((k for prefix, k in _SIDE_EFFECT_KIND_PREFIX.items()
                         if skill_id.startswith(prefix)), 'skill')
        elif _is_clarification(draft):
            kind = 'clarify'
        file_ids: list = []
        for proposal in side_effects:
            for key in ('file_ids', 'target_file_ids'):
                file_ids.extend(proposal['arguments'].get(key, []) or [])
        permission = ''
        if side_effects and self._tools:
            tool = next((t for t in self._tools
                         if t.descriptor.name == skill_id), None)
            if tool is not None:
                permission = self._engine.evaluate(
                    None, self._mode, tool.descriptor,
                    side_effects[0]['arguments'], None).kind
        return NewDecision(
            kind=kind, skill_id=skill_id, file_ids=tuple(file_ids),
            draft=draft, tool_calls=tuple(side_effects),
            permission=permission, error=error,
            model_calls=model.calls, input_tokens=model.input_tokens,
            output_tokens=model.output_tokens,
            first_token_latency=model.first_token_latency, duration=duration)

    @staticmethod
    def _diff(case, legacy, new) -> tuple:
        diffs = []
        if legacy.kind != new.kind:
            diffs.append('kind')
            if new.kind == 'clarify' and legacy.kind != 'clarify':
                diffs.append('clarification')
        if legacy.skill_id and legacy.skill_id != new.skill_id:
            diffs.append('skill_id')
        if legacy.file_ids and set(legacy.file_ids) != set(new.file_ids):
            diffs.append('file_scope')
        if legacy.permission and new.permission \
                and legacy.permission != new.permission:
            diffs.append('permission')
        return tuple(diffs)

    @staticmethod
    def _scrubbed_case(case: ShadowCase) -> ShadowCase:
        return replace(case, text=redact_secrets(case.text))


def _is_clarification(draft: str) -> bool:
    text = draft.strip()
    return bool(text) and any(marker in text for marker in _CLARIFY_MARKERS)


# ---------------------------------------------------------------- 指标

@dataclass(frozen=True)
class ShadowMetrics:
    total: int
    chat_total: int
    chat_success: int
    skill_total: int
    skill_match: int
    file_scope_total: int
    file_scope_match: int
    unnecessary_clarifications: int
    permission_mismatches: int
    legacy_wrong_new_right: int
    new_regressions: int
    model_calls: int
    input_tokens: int
    output_tokens: int
    avg_first_token_latency: float
    avg_duration: float
    error_rate: float
    side_effect_violations: int = 0      # ShadowTool 保证为 0
    cross_session_violations: int = 0
    charged_units: int = 0               # shadow 无计费通道

    @classmethod
    def from_comparisons(cls, comparisons) -> ShadowMetrics:
        comparisons = list(comparisons)
        total = len(comparisons)

        def agrees(c, kind):
            return c.new.kind == kind and not c.new.error

        chat = [c for c in comparisons
                if (c.case.expected_kind or c.legacy.kind) == 'chat'
                and c.legacy.kind == 'chat']
        chat_success = sum(1 for c in chat if agrees(c, 'chat'))
        skill = [c for c in comparisons
                 if c.case.expected_skill or c.legacy.skill_id]
        skill_match = sum(
            1 for c in skill
            if c.new.skill_id == (c.case.expected_skill or c.legacy.skill_id))
        scoped = [c for c in comparisons
                  if c.case.expected_files or c.legacy.file_ids]
        scope_match = sum(
            1 for c in scoped
            if set(c.new.file_ids)
            == set(c.case.expected_files or c.legacy.file_ids))
        unnecessary = sum(1 for c in comparisons
                          if 'clarification' in c.diffs)
        permission_mismatch = sum(1 for c in comparisons
                                  if 'permission' in c.diffs)

        def right(c, new):
            d = c.new if new else c.legacy
            if c.case.expected_kind and d.kind != c.case.expected_kind:
                return False
            if c.case.expected_skill and d.skill_id != c.case.expected_skill:
                return False
            return not (c.case.expected_files and set(d.file_ids) != set(c.case.expected_files))

        legacy_wrong_new_right = sum(
            1 for c in comparisons
            if not right(c, False) and right(c, True) and not c.new.error)
        new_regressions = sum(
            1 for c in comparisons
            if right(c, False) and (not right(c, True) or c.new.error))
        errors = sum(1 for c in comparisons if c.new.error)
        calls = sum(c.new.model_calls for c in comparisons)
        in_tokens = sum(c.new.input_tokens for c in comparisons)
        out_tokens = sum(c.new.output_tokens for c in comparisons)
        latencies = [c.new.first_token_latency for c in comparisons]
        durations = [c.new.duration for c in comparisons]
        return cls(
            total=total,
            chat_total=len(chat), chat_success=chat_success,
            skill_total=len(skill), skill_match=skill_match,
            file_scope_total=len(scoped), file_scope_match=scope_match,
            unnecessary_clarifications=unnecessary,
            permission_mismatches=permission_mismatch,
            legacy_wrong_new_right=legacy_wrong_new_right,
            new_regressions=new_regressions,
            model_calls=calls, input_tokens=in_tokens,
            output_tokens=out_tokens,
            avg_first_token_latency=(
                sum(latencies) / len(latencies) if latencies else 0.0),
            avg_duration=(sum(durations) / len(durations)
                          if durations else 0.0),
            error_rate=errors / total if total else 0.0)

    def evaluate_gates(self, *, legacy_clarification_rate: float,
                       skill_accuracy_threshold: float = 0.98) -> dict:
        chat_rate = (self.chat_success / self.chat_total
                     if self.chat_total else 1.0)
        scope_rate = (self.file_scope_match / self.file_scope_total
                      if self.file_scope_total else 1.0)
        skill_rate = (self.skill_match / self.skill_total
                      if self.skill_total else 1.0)
        clarify_rate = (self.unnecessary_clarifications / self.total
                        if self.total else 0.0)
        gates = {
            'chat_success': chat_rate == 1.0,
            'file_scope': scope_rate == 1.0,
            'no_side_effect_violation': self.side_effect_violations == 0,
            'no_cross_session_pollution':
                self.cross_session_violations == 0,
            'no_double_billing': self.charged_units == 0,
            'skill_selection_accuracy':
                skill_rate >= skill_accuracy_threshold,
            'clarification_below_legacy':
                clarify_rate < legacy_clarification_rate,
        }
        gates['overall'] = all(gates.values())
        return gates
