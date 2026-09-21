"""Model configuration loader.

The standalone agent intentionally reuses local Codex/OpenAI-compatible
configuration where possible so the agent can run with the same API endpoint
and API key that local Codex uses.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[3]
USER_CONFIG_PATH = Path.home() / ".ai-excel-agent" / "model_config.json"
PROJECT_CONFIG_PATH = PROJECT_ROOT / "config" / "agent_config.json"
MODEL_CONFIG_KEYS = ("api_base", "api_key", "model", "provider")


def load_model_config() -> dict[str, Any]:
    project_config = _read_json(PROJECT_CONFIG_PATH)
    codex_config = _read_codex_config()
    user_config = _read_json(USER_CONFIG_PATH)
    env_config = {
        "api_base": os.environ.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_API_BASE") or "",
        "api_key": os.environ.get("OPENAI_API_KEY") or "",
        "model": os.environ.get("OPENAI_MODEL") or "",
        "provider": os.environ.get("AI_EXCEL_AGENT_PROVIDER") or "",
    }
    # Requirement: environment > user config > project config. Local Codex config
    # is treated as the user's model config source when explicit user config does
    # not override it.
    merged = {key: "" for key in MODEL_CONFIG_KEYS}
    for source in [project_config, codex_config, user_config, env_config]:
        for key, value in source.items():
            if value:
                merged[key] = value
    merged["sources"] = {
        "project_config": str(PROJECT_CONFIG_PATH),
        "user_config": str(USER_CONFIG_PATH),
        "codex_config_dir": str(Path.home() / ".codex"),
    }
    if _is_official_deepseek_url(str(merged.get("api_base") or "")):
        merged["provider"] = "deepseek"
        merged["wire_api"] = "chat_completions"
    return merged


def _read_codex_config() -> dict[str, str]:
    codex_dir = Path.home() / ".codex"
    candidates = [codex_dir / "config.json", codex_dir / "auth.json", codex_dir / "config.toml"]
    result = {key: "" for key in MODEL_CONFIG_KEYS}
    for path in candidates:
        data = _read_json(path)
        if path.suffix.lower() == ".toml":
            data = _flatten_codex_toml(data)
        result["api_base"] = result["api_base"] or str(
            data.get("api_base")
            or data.get("base_url")
            or data.get("OPENAI_BASE_URL")
            or data.get("OPENAI_API_BASE")
            or ""
        )
        result["api_key"] = result["api_key"] or str(
            data.get("api_key") or data.get("OPENAI_API_KEY") or ""
        )
        result["model"] = result["model"] or str(
            data.get("model") or data.get("OPENAI_MODEL") or ""
        )
        provider = data.get("provider")
        if provider:
            result["provider"] = result["provider"] or str(provider)
        if data.get("wire_api"):
            result["wire_api"] = str(data.get("wire_api"))
    return result


def _flatten_codex_toml(data: dict[str, Any]) -> dict[str, Any]:
    flattened = dict(data)
    provider_name = data.get("model_provider")
    providers = data.get("model_providers") or {}
    provider_data = providers.get(provider_name, {}) if provider_name else {}
    if provider_data:
        flattened["base_url"] = flattened.get("base_url") or provider_data.get("base_url")
        flattened["wire_api"] = flattened.get("wire_api") or provider_data.get("wire_api")
        flattened["provider"] = "openai-compatible"
    return flattened


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    if path.suffix.lower() == ".toml":
        return _read_toml(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_toml(path: Path) -> dict[str, Any]:
    try:
        import tomllib

        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _is_official_deepseek_url(api_base: str) -> bool:
    return (urlparse(api_base.strip()).hostname or "").lower() == "api.deepseek.com"
