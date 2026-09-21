"""ContextBuilder：按任务书 10.1 的固定顺序装配模型上下文。

系统安全规则 → Agent 行为规则 → 权限快照 → Tool 描述 → Skill 固定规则
→ 项目 confirmed facts → 最近有效 compaction → 当前 lane 最近 Turns
→ 本轮文件摘要 → 当前用户消息。

10.2 排除项：其他 lane 消息（lane_history 父链天然隔离）、秘密（遮蔽）、
原始本地路径（文件摘要用 id 不用路径）、未确认推测（只取 confirmed facts）、
与本轮无关的历史 Run 绑定（只取当前 operation 的 explicit 绑定）。
"""
from dataclasses import dataclass, field

from .compaction import source_fingerprint
from .text_safety import redact_secrets

DEFAULT_SYSTEM_RULES = (
    '【系统安全规则】原件只读；密钥不出库；未授权的外部副作用一律禁止；'
    '模型文本不代表授权。')
DEFAULT_BEHAVIOR_RULES = (
    '【Agent 行为规则】先澄清再执行；工具失败如实报告；只向用户展示最终成果；'
    '本轮上传与勾选的文件必须优先使用；项目历史资料不默认带入上下文，'
    '但任务需要或用户明确要求时，应通过文件工具主动读取使用，'
    '不得声称拿不到项目文件。')


@dataclass
class BuiltContext:
    messages: tuple
    report: dict = field(default_factory=dict)


class ContextBuilder:
    def __init__(self, *, token_budget=8000,
                 system_rules=DEFAULT_SYSTEM_RULES,
                 behavior_rules=DEFAULT_BEHAVIOR_RULES, token_estimator=None):
        self.token_budget = token_budget
        self.system_rules = system_rules
        self.behavior_rules = behavior_rules
        self._estimate = token_estimator or (lambda text: max(1, len(text)))

    def build(self, *, repo, operation, tools=()):
        session_id, lane_id = operation.session_id, operation.lane_id
        report = {'budget': self.token_budget, 'dropped_entries': 0,
                  'compaction_used': False}
        mode = repo.session_permission_mode(session_id)
        project_id = repo.session_project_id(session_id)
        sections = [
            self._system(self.system_rules),
            self._system(self.behavior_rules),
            self._system(f'【当前权限快照】模式：{mode}；每次工具调用以 PolicyEngine 实时决定为准。'),
        ]
        if tools:
            listing = '；'.join(f'{t.descriptor.name}({t.descriptor.risk})'
                                for t in tools)
            sections.append(self._system(f'【当前 Tool 描述】{listing}'))
        snapshot = repo.resource_snapshot(operation.id)
        if snapshot:
            pinned = '；'.join(
                f"{item.get('skill_id', item.get('id', 'unknown'))}@{item.get('version', 'builtin')}"
                for item in snapshot if item.get('kind', 'skill') == 'skill')
            if pinned:
                sections.append(self._system(f'【Skill 固定规则】{pinned}（版本已锁定）'))
        facts = repo.facts(project_id, status='confirmed')
        project_facts = [f for f in facts if f.get('scope') != 'user']
        user_facts = [f for f in facts if f.get('scope') == 'user']
        if project_facts:
            rendered = '；'.join(f"{f['fact_key']}={f['value']}"
                                 for f in project_facts)
            sections.append(self._system(f'【项目 confirmed overlay】{rendered}'))
        if user_facts:
            rendered = '；'.join(f"{f['fact_key']}={f['value']}"
                                 for f in user_facts)
            sections.append(self._system(f'【用户 preference overlay】{rendered}'))
        history = list(repo.lane_history(session_id, lane_id))
        compaction = self._valid_compaction(repo, session_id, lane_id, history)
        if compaction is not None:
            report['compaction_used'] = True
            summary = next(e for e in history
                           if e.id == compaction['summary_entry_id'])
            sections.append({'role': 'context_summary',
                             'payload': {'text': summary.payload.get('text', '')}})
            end_sequence = next(e.sequence for e in history
                                if e.id == compaction['source_end_entry_id'])
            history = [e for e in history if e.sequence > end_sequence]
        # context_summary 只经“最近有效压缩”段落注入，原始摘要条目不重放
        history = [e for e in history if e.entry_type != 'context_summary']
        entries = [{'role': e.entry_type, 'payload': self._clean(e.payload)}
                   for e in history]
        bindings = repo.operation_files(operation.id)
        lines = '；'.join(
            f"{b.get('name') or b['file_id']}({b['binding_kind']})"
            for b in bindings)
        file_section = self._system(
            f'【本轮文件摘要】{lines}' if lines else '【本轮文件摘要】无')
        history_section = self._history_section(
            repo, project_id, {b['file_id'] for b in bindings})
        tail = [file_section] + ([history_section] if history_section else [])
        kept, dropped, tokens = self._fit(sections, tail, entries)
        report['dropped_entries'] = dropped
        report['tokens'] = tokens
        if entries:
            messages = (*sections, *kept, *tail, entries[-1])
        else:
            messages = (*sections, *tail)
        return BuiltContext(messages=tuple(messages), report=report)

    # ------------------------------------------------------------ internals

    def _history_section(self, repo, project_id, bound_ids, *, limit=20):
        """项目历史资料可发现清单：只列名称不代入内容，取用由 Agent 决定。"""
        if not project_id:
            return None
        lookup = getattr(repo, 'legacy_project_files', None)
        if lookup is None:
            return None
        try:
            records = lookup(project_id)
        except Exception:  # noqa: BLE001 - 清单只是提示，不得拖垮上下文装配
            return None
        names = [r['name'] for r in records
                 if r.get('name') and r.get('id') not in bound_ids]
        if not names:
            return None
        shown = '；'.join(names[:limit])
        count = (f' 等共 {len(names)} 个' if len(names) > limit
                 else f'（共 {len(names)} 个）')
        return self._system(
            '【项目历史资料】以下文件不在本轮上下文；任务需要或用户明确要求时，'
            '可用 inspect_project_files 核对并通过文件工具读取使用：'
            + shown + count)

    @staticmethod
    def _system(text):
        return {'role': 'system', 'payload': {'text': text}}

    @staticmethod
    def _clean(payload):
        cleaned = dict(payload or {})
        for key in ('text', 'content'):
            if isinstance(cleaned.get(key), str):
                cleaned[key] = redact_secrets(cleaned[key])
        return cleaned

    def _valid_compaction(self, repo, session_id, lane_id, history):
        record = repo.latest_compaction(session_id, lane_id)
        if record is None:
            return None
        ids = [e.id for e in history]
        try:
            start = ids.index(record['source_start_entry_id'])
            end = ids.index(record['source_end_entry_id'])
        except ValueError:
            return None
        if end < start:
            return None
        if source_fingerprint(history[start:end + 1]) != record['source_sha256']:
            return None  # 源已被篡改/改写：压缩作废，回到完整历史
        return record

    def _fit(self, sections, tail_sections, entries):
        fixed = [*sections, *tail_sections]
        if entries:
            fixed.append(entries[-1])
        tokens = sum(self._estimate(str(m['payload'])) for m in fixed)
        tail = entries[:-1]
        kept = []
        for message in reversed(tail):
            cost = self._estimate(str(message['payload']))
            if tokens + cost > self.token_budget:
                break
            kept.append(message)
            tokens += cost
        kept.reverse()
        return kept, len(tail) - len(kept), tokens
