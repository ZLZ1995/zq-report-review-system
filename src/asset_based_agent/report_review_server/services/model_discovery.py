"""Read-only model discovery. No prompts, billing calls, or plaintext persistence."""

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
from urllib.parse import urlsplit, urlunsplit

from .auth_service import ServiceError


def normalize_url(value: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(value.strip())
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment
                or parsed.port not in (None, 443)):
            raise ValueError()
        host = parsed.hostname.encode("idna").decode("ascii")
        path = parsed.path.rstrip("/")
        for suffix in ("/chat/completions", "/models"):
            path = path.removesuffix(suffix)
        provider = "deepseek" if host == "api.deepseek.com" else "openai_compatible"
        if not path and provider != "deepseek":
            path = "/v1"
        return urlunsplit(("https", host, path, "", "")), provider
    except (ValueError, UnicodeError):
        raise ServiceError("discovery_url", "请输入有效的公网 HTTPS API 地址（443端口，不含账号或查询参数）。", 422) from None


def fingerprint(url: str, key: str) -> str:
    return hashlib.sha256(json.dumps([url, key], ensure_ascii=True).encode()).hexdigest()


class _PinnedHTTPS(http.client.HTTPSConnection):
    """Pin the validated IP while preserving hostname verification and SNI."""

    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), timeout=self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise


def fetch_models(base_url: str, api_key: str) -> list[str]:
    base_url, _ = normalize_url(base_url)
    parsed = urlsplit(base_url)
    if not api_key.strip() or any(ord(c) < 32 or ord(c) > 126 for c in api_key):
        raise ServiceError("discovery_key", "API Key 为空或包含无效字符。", 422)
    connection = None
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(ip).is_global for ip in addresses):
            raise ServiceError("discovery_url", "不允许连接本机、内网或保留地址。", 422)
        connection = _PinnedHTTPS(parsed.hostname, min(addresses))
        connection.request("GET", parsed.path + "/models", headers={
            "Authorization": "Bearer " + api_key, "Accept": "application/json",
        })
        response = connection.getresponse()
        if response.status != 200:
            messages = {401: "API Key 无效或已过期。", 403: "该 Key 无权获取模型列表。",
                        404: "此 API 地址未提供模型列表接口，请核对地址。", 429: "渠道请求受限，请稍后重试。"}
            raise ServiceError("discovery_failed", messages.get(response.status, "渠道未返回成功响应，请核对地址或稍后重试。"), 502)
        raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ValueError()
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise TypeError()
        if payload.get("has_more") or payload.get("next"):
            raise ServiceError("discovery_pagination", "此渠道返回分页模型列表，暂不支持；未将不完整清单作为全部模型。", 502)
        models = []
        for item in payload["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str):
                raise TypeError()
            name = item["id"].strip()
            if not name or len(name) > 128 or any(ord(c) < 32 for c in name):
                raise ValueError()
            if name not in models:
                models.append(name)
        if not models:
            raise ServiceError("discovery_empty", "连接成功，但该 Key 没有可选模型。", 502)
        return models
    except (OSError, http.client.HTTPException):
        raise ServiceError("discovery_network", "连接失败或超时，请检查地址、网络及 HTTPS 证书。", 502) from None
    except (ValueError, TypeError, UnicodeError):
        raise ServiceError("discovery_format", "渠道未返回有效的标准模型清单。", 502) from None
    finally:
        if connection is not None:
            connection.close()
