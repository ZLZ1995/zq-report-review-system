"""Read-only release metadata and public server protocol inspection."""

from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .skills import REVIEW, digest

CLIENT_VERSION = "0.2.3"


def local_release() -> dict:
    return {
        "client_version": CLIENT_VERSION,
        "review_skill_version": REVIEW.version,
        "review_rules_sha256": digest(Path(__file__).with_name("review_rules.txt")),
    }


def inspect_server(base_url: str, *, client: httpx.Client | None = None) -> dict:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("版本检查要求 HTTPS 服务地址")
    url = f"{parsed.scheme}://{parsed.netloc}/openapi.json"
    if client is None:
        with httpx.Client(timeout=15) as owned:
            return inspect_server(base_url, client=owned)
    response = client.get(url)
    response.raise_for_status()
    data = response.json()
    properties = data.get("components", {}).get("schemas", {}).get(
        "ReviewJobCreateRequest", {}
    ).get("properties", {})
    return {
        "server_api_version": str(data.get("info", {}).get("version", "未提供")),
        "server_build": "未提供",
        "user_request_supported": properties.get("user_request", {}).get("type") == "string",
    }
