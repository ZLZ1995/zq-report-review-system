"""S4-02 Provider Route URL / SSRF 防护（先红后绿）。

create_route 直接保存 base_url 且服务端随后对其发 HTTP 请求；
必须拒绝非 https、URL 内账号、localhost/loopback/link-local/私网
（IPv4+IPv6），除非命中显式企业 allowlist。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from asset_based_agent.report_review_server.models import ModelDefinition
from asset_based_agent.report_review_server.services.auth_service import (
    ServiceError,
)
from asset_based_agent.report_review_server.services.model_admin_service import (
    ModelAdminService,
)

_RATES = dict.fromkeys(
    ['input', 'output', 'cache_hit', 'cache_miss', 'reasoning'], '1')


def _model(client):
    with client.app.state.session_factory() as db:
        model = ModelDefinition(
            code='ssrf-model', display_name='SSRF Model', tier='standard',
            enabled=True, model_multiplier=Decimal(1),
            max_output_tokens=1024)
        db.add(model)
        db.commit()
        return model.model_id


def _create(client, model_id, url, *, priority=1, service=None):
    svc = service or client.app.state.model_admin_service
    with client.app.state.session_factory() as db:
        return svc.create_route(
            db, model_id=model_id, provider_type='openai_compatible',
            provider_model='m', base_url=url, api_key='k',
            priority=priority, timeout_seconds=30, rates=dict(_RATES))


@pytest.mark.parametrize('url', [
    'http://api.example.com',              # 仅 https
    'https://user:pass@api.example.com',   # URL 内账号
    'https://localhost',                   # localhost
    'https://localhost.localdomain',
    'https://127.0.0.1',                   # IPv4 loopback
    'https://127.55.0.9',
    'https://[::1]',                       # IPv6 loopback
    'https://10.0.0.8',                    # IPv4 私网
    'https://172.16.3.4',
    'https://192.168.1.1',
    'https://169.254.169.254',             # 云元数据（link-local）
    'https://[fe80::1]',                   # IPv6 link-local
    'https://[fd12::8]',                   # IPv6 ULA 私网
    'https://0.0.0.0',
    'https://100.64.0.1',                  # CGNAT 非公网
    'https://gateway.internal',            # 内网域名后缀
])
def test_create_route_rejects_ssrf_urls(client, url):
    model_id = _model(client)
    with pytest.raises(ServiceError) as excinfo:
        _create(client, model_id, url)
    assert excinfo.value.code == 'invalid_provider_url'
    assert excinfo.value.status_code == 422


@pytest.mark.parametrize('url', [
    'https://api.deepseek.com',
    'https://example.com',
    'https://relay.example.com:8443/v1',
    'https://8.8.8.8',                     # 公网 IP 字面量允许
])
def test_create_route_allows_public_https(client, url):
    model_id = _model(client)
    route = _create(client, model_id, url)
    assert route.base_url.startswith('https://')


def test_create_route_allowlist_permits_enterprise_private_host(client):
    """显式企业 allowlist 命中时放行私网地址。"""
    model_id = _model(client)
    cipher = client.app.state.model_admin_service.cipher
    service = ModelAdminService(cipher, url_allowlist=frozenset({'10.0.0.8'}))
    route = _create(client, model_id, 'https://10.0.0.8', service=service)
    assert route.base_url == 'https://10.0.0.8'
    # allowlist 不豁免 https / userinfo 基本规则
    with pytest.raises(ServiceError):
        _create(client, model_id, 'https://user:pass@10.0.0.8',
                priority=2, service=service)
