"""秘密与敏感信息的确定性检测与遮蔽（任务书 10.2/6.9）。"""
import re

_KEY_PATTERN = re.compile(
    r'(?i)(password|passwd|pwd|token|api[_-]?key|secret|authorization|bearer)'
    r'["\']?\s*[:=：]\s*["\']?[^\s，。；;"\']+')
_VALUE_PATTERN = re.compile(r'(?i)\bsk-[A-Za-z0-9]{6,}')

REDACTED = '[已遮蔽]'


def contains_secret(text) -> bool:
    text = str(text)
    return bool(_KEY_PATTERN.search(text) or _VALUE_PATTERN.search(text))


def redact_secrets(text: str) -> str:
    result = _KEY_PATTERN.sub(lambda m: f'{m.group(1)}={REDACTED}', str(text))
    return _VALUE_PATTERN.sub(REDACTED, result)
