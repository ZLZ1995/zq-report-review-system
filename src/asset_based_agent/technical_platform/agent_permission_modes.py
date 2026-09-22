"""Account-level Agent approval policy shared by every platform capability.

The selected mode changes when the native UI asks for approval.  It never
changes task identity, project/file scope, credential isolation, cancellation,
or the rule that model/page content cannot grant itself authority.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionMode:
    id: str
    title: str
    description: str


_MODES = (
    PermissionMode('request', '请求批准', '编辑或生成文件、安装能力包和使用互联网时询问'),
    PermissionMode('risk', '帮我批准', '仅对可能修改数据、使用凭据或扩展能力的操作询问'),
    PermissionMode('full', '范围内自动执行', '在当前任务、项目与已安装能力范围内默认执行'),
)
_MODE_IDS = frozenset(item.id for item in _MODES)
_OPERATIONS = frozenset({
    'network', 'generate_file', 'modify_file', 'install_skill', 'software_update',
    'browser_observe', 'browser_write', 'credential_use', 'upload', 'download',
})
_RISKY = frozenset({
    'modify_file', 'install_skill', 'software_update', 'browser_write',
    'credential_use', 'upload', 'download',
})


def permission_mode_options() -> tuple[PermissionMode, ...]:
    return _MODES


def validate_permission_mode(mode: object) -> str:
    if not isinstance(mode, str) or mode not in _MODE_IDS:
        raise ValueError('Unknown Agent permission mode')
    return mode


def requires_confirmation(mode: object, operation: str) -> bool:
    mode = validate_permission_mode(mode)
    if operation not in _OPERATIONS:
        raise ValueError('Unknown Agent operation')
    if mode == 'full':
        return False
    if mode == 'request':
        return True
    return operation in _RISKY


def browser_operation(action: str) -> str:
    mapping = {
        'observe': 'browser_observe', 'navigate': 'browser_observe',
        'scroll': 'browser_observe', 'wait': 'browser_observe',
        'click': 'browser_write', 'fill': 'browser_write', 'select': 'browser_write',
        'login': 'credential_use', 'upload': 'upload', 'download': 'download',
    }
    try:
        return mapping[action]
    except KeyError as exc:
        raise ValueError('Unknown browser action') from exc


def requires_browser_confirmation(mode: object, action: str) -> bool:
    return requires_confirmation(mode, browser_operation(action))
