"""规则引擎：三档模式 × 11 风险维度的静态矩阵 + 文件范围约束。

- 请求批准（request）：本地只读自动允许，其余一律询问；
- 帮我批准（assisted）：只读与可恢复操作自动允许，高风险写入/上传/
  凭据/浏览器/进程/更新询问；
- 完全访问（full）：范围内允许，但原件修改永远拒绝、凭据与更新永远询问；
- 路径范围：写入类工具的目标路径超出 FileScope 时不得自动允许。
"""
from pathlib import Path

from ..agent_core.contracts import TOOL_RISKS
from .contracts import PERMISSION_MODES, PolicyDecision
from .receipts import ReceiptService

# 原件只读是平台硬规则：任何模式都不允许。
_ALWAYS_DENY = frozenset({'original_modify'})
# 凭据与软件更新即使在完全访问模式下也必须逐项确认（密钥保护）。
_ALWAYS_ASK = frozenset({'credential', 'update'})
_ASSISTED_ALLOW = frozenset(
    {'local_readonly', 'local_create', 'copy_modify', 'network_read'})
_FULL_ALLOW = _ASSISTED_ALLOW | frozenset(
    {'network_write', 'browser_action', 'external_upload', 'process'})
_SCOPE_SENSITIVE = frozenset({'local_create', 'copy_modify', 'original_modify'})
_PATH_KEYS = ('directory', 'path', 'output', 'destination', 'target_dir')


class RuleBasedPolicyEngine:
    """默认策略引擎；grants_resolver 由业务层注入（如生成类 Skill 的授予集合）。"""

    def __init__(self, *, grants_resolver=None, receipts=None):
        self._grants_resolver = grants_resolver \
            or (lambda tool, arguments: ('read_selected_files',))
        self.receipts = receipts or ReceiptService()

    def evaluate(self, principal, mode, tool, arguments, file_scope):
        if tool.risk not in TOOL_RISKS:
            return PolicyDecision('deny', f'未声明的风险等级: {tool.risk}')
        if tool.risk in _ALWAYS_DENY:
            return PolicyDecision('deny', '平台禁止修改原件')
        if tool.risk in _ALWAYS_ASK:
            return self._ask(tool, arguments, '凭据与更新操作需要逐项确认')
        normalized = mode if mode in PERMISSION_MODES else 'request'
        if normalized == 'request':
            allowed = tool.risk == 'local_readonly'
        elif normalized == 'assisted':
            allowed = tool.risk in _ASSISTED_ALLOW
        else:
            allowed = tool.risk in _FULL_ALLOW
        if allowed and self._out_of_scope(tool, arguments or {}, file_scope):
            return self._ask(tool, arguments, '路径超出已授权文件范围，需要用户确认')
        if allowed:
            return PolicyDecision('allow', grants=self._grants(tool, arguments))
        return self._ask(tool, arguments,
                         f'{normalized} 模式下 {tool.risk} 操作需要用户批准')

    def _ask(self, tool, arguments, reason):
        return PolicyDecision('ask', reason, grants=self._grants(tool, arguments))

    def _grants(self, tool, arguments):
        return tuple(str(g) for g in self._grants_resolver(tool, arguments or {}))

    @staticmethod
    def _out_of_scope(tool, arguments, file_scope):
        if file_scope is None or not getattr(file_scope, 'roots', ()):
            return False
        if tool.risk not in _SCOPE_SENSITIVE:
            return False
        roots = [Path(root).resolve() for root in file_scope.roots]
        for key in _PATH_KEYS:
            value = arguments.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            candidate = Path(value).resolve()
            if not any(candidate == root or candidate.is_relative_to(root)
                       for root in roots):
                return True
        return False
