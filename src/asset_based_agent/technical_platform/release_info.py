"""Read-only release metadata and public server protocol inspection."""

import re
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from .local_migrations import SCHEMA_VERSION
from .skills import BUILTINS, GENERATORS, REVIEW, digest

CLIENT_VERSION = "0.2.10"
CLIENT_RELEASE_SEQUENCE = 5
UPDATER_VERSION = "0.2.10"


def local_release(*, store=None) -> dict:
    from .generation import bundle_fingerprint, locked_template
    from .skill_contracts import builtin_contracts
    contracts = builtin_contracts()
    skills = []
    for spec in BUILTINS:
        item = {'id': spec.id, 'version': spec.version, 'status': 'builtin'}
        if spec in GENERATORS:
            try:
                item.update(status='verified', bundle_sha256=bundle_fingerprint(spec.id))
                if contracts[spec.id].locked_template:
                    template = locked_template(spec.id)
                    item['template_sha256'] = digest(template)
            except (OSError, ValueError, KeyError, TypeError):
                item['status'] = 'unavailable_or_changed'
        skills.append(item)
    external = []
    external_status = 'not_checked'
    if store is not None:
        from .skill_installation import SkillInstallation
        try:
            external = SkillInstallation(store, initialize=False).release_inventory()
            external_status = 'checked'
        except (sqlite3.Error, OSError, ValueError):
            external_status = 'unavailable'
    return {
        "client_version": CLIENT_VERSION,
        "protocol_version": 1,
        "local_schema_version": SCHEMA_VERSION,
        "skills": skills,
        "external_skills": external,
        "external_skills_status": external_status,
        "review_skill_version": REVIEW.version,
        "review_rules_sha256": digest(Path(__file__).with_name("review_rules.txt")),
    }


def release_details(info: dict) -> str:
    """Human-readable, local-only metadata; no project paths or credentials."""
    lines = [f"客户端支持的数据版本：{info['local_schema_version']}（不代表项目已迁移）",
             f"客户端协议：{info['protocol_version']}",
             f"审核规则 SHA256：{info['review_rules_sha256']}"]
    for skill in info['skills']:
        status = {'verified': '锁定模板校验通过', 'builtin': '内置',
                  'unavailable_or_changed': '资源缺失或变更，不能确认'}.get(skill['status'], '未知')
        lines.append(f"{skill['id']} {skill['version']}：{status}")
        for name in ('template_sha256', 'bundle_sha256'):
            if name in skill:
                lines.append(f"  {name}: {skill[name]}")
    external_status = info.get('external_skills_status', 'not_checked')
    lines.append('外部 Skill：' + {'checked': '已检查（兼容不代表执行授权）',
                                'not_checked': '未检查', 'unavailable': '无法确认'}.get(
                                    external_status, '无法确认'))
    for skill in info.get('external_skills', []):
        status = {'disabled': '已安装，未启用', 'dependencies_missing': '依赖不满足',
                  'enabled_compatible': '已启用，包兼容',
                  'unavailable_or_changed': '完整性或格式异常'}.get(skill['status'], '无法确认')
        lines.append(f"{skill['id']} {skill['version']}：{status}")
        if 'package_sha256' in skill:
            lines.append(f"  package_sha256: {skill['package_sha256']}")
    return '\n'.join(lines)


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
    result = {
        "server_api_version": str(data.get("info", {}).get("version", "未提供")),
        "server_build": "未提供",
        "user_request_supported": properties.get("user_request", {}).get("type") == "string",
        "protocol_version": None,
        "capabilities": {},
        "current_release": None,
    }
    if 'get' in data.get('paths', {}).get('/api/v1/capabilities', {}):
        response = client.get(f'{parsed.scheme}://{parsed.netloc}/api/v1/capabilities')
        response.raise_for_status()
        metadata = response.json()
        if (not isinstance(metadata, dict) or type(metadata.get('schema_version')) is not int or
                metadata['schema_version'] != 1 or type(metadata.get('protocol_version')) is not int or
                metadata['protocol_version'] != 1):
            raise ValueError('服务端协议版本不兼容，请联系管理员升级。')
        capabilities = metadata.get('capabilities')
        build = metadata.get('build_sha')
        if (not isinstance(capabilities, dict) or len(capabilities) > 100 or
                any(not isinstance(k, str) or not re.fullmatch(r'[a-z_]{1,64}', k) or
                    type(v) is not int or not 1 <= v <= 100 for k, v in capabilities.items()) or
                (build is not None and (not isinstance(build, str) or
                                       not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}', build)))):
            raise ValueError('服务端协议元信息无效，已停止兼容性确认。')
        result.update(server_build=build or '未提供', protocol_version=1, capabilities=capabilities)
        if capabilities.get('client_release') == 1:
            release_response = client.get(f'{parsed.scheme}://{parsed.netloc}/api/v1/client-releases/current')
            if release_response.status_code != 404:
                release_response.raise_for_status()
                release = release_response.json()
                if (not isinstance(release, dict) or not isinstance(release.get('manifest'), dict)
                        or not isinstance(release.get('manifest_sha256'), str)
                        or len(release['manifest_sha256']) != 64):
                    raise ValueError('服务端发布清单无效，已停止更新检查。')
                result['current_release'] = release
    return result
