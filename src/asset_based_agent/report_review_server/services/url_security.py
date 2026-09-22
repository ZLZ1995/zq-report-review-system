"""Provider base_url SSRF 防护（S4-02）。

create_route 保存的 base_url 会被服务端用于出站 HTTP 请求；管理员误配置
或被诱导配置内网地址会形成 SSRF。规则：仅 https、URL 不得携带账号、
禁止 localhost / loopback / link-local / 私网与保留地址（IPv4+IPv6），
除非命中显式企业 allowlist（REPORT_REVIEW_PROVIDER_URL_ALLOWLIST）。

DNS rebinding 说明：配置期解析无法防御后续 rebinding；需要严格保证的
部署应使用固定 allowlist 收敛可用主机。
"""
from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from .auth_service import ServiceError

_BLOCKED_HOSTNAMES = frozenset({
    'localhost', 'ip6-localhost', 'broadcasthost',
})
_BLOCKED_SUFFIXES = (
    '.localhost', '.localdomain', '.local', '.internal', '.lan', '.home',
    '.corp', '.intranet',
)


def validate_provider_base_url(
    base_url: str,
    *,
    allowed_hosts: frozenset[str] = frozenset(),
) -> str:
    """校验并返回去空白后的 base_url；非法一律 invalid_provider_url/422。"""
    value = base_url.strip()
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or '').lower().rstrip('.')
        has_userinfo = parsed.username is not None or parsed.password is not None
    except ValueError:
        raise ServiceError(
            'invalid_provider_url', '渠道地址不是合法 URL。', 422) from None
    if parsed.scheme != 'https':
        raise ServiceError(
            'invalid_provider_url', '渠道地址必须使用 HTTPS。', 422)
    if not host:
        raise ServiceError(
            'invalid_provider_url', '渠道地址缺少主机名。', 422)
    if has_userinfo:
        raise ServiceError(
            'invalid_provider_url', '渠道地址不得携带账号信息。', 422)
    if host in allowed_hosts:
        return value  # 显式企业 allowlist 放行（仍需 https + 无账号）
    if host in _BLOCKED_HOSTNAMES or host.endswith(_BLOCKED_SUFFIXES):
        raise ServiceError(
            'invalid_provider_url', '渠道地址不得指向本机或内网主机。', 422)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ServiceError(
            'invalid_provider_url',
            '渠道地址不得指向本机、内网或保留地址。', 422)
    return value
