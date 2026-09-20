"""Release-gate contract check: /capabilities must agree with the OpenAPI schema.

The client negotiates field-level extensions through named capabilities. If the
server advertises a capability whose schema is absent from OpenAPI — or ships a
schema without advertising the capability — clients cannot negotiate reliably.
This check fails the build/deploy acceptance in both directions.
"""
from __future__ import annotations

from typing import Any

# capability -> schema requirements in the OpenAPI document
CAPABILITY_SCHEMA_REQUIREMENTS: dict[str, dict[str, Any]] = {
    'material_evidence': {
        'schemas': ('MaterialEvidence',),
        'schema_properties': {'EvidenceRef': ('evidence',)},
    },
}


def check_capabilities_against_openapi(capabilities_doc: dict[str, Any],
                                       openapi_doc: dict[str, Any]) -> list[str]:
    """Return human-readable consistency issues; empty list means consistent."""
    issues: list[str] = []
    if not isinstance(capabilities_doc, dict):
        return ['capabilities 文档不是 JSON 对象']
    if not isinstance(openapi_doc, dict):
        return ['OpenAPI 文档不是 JSON 对象']
    for key in ('schema_version', 'protocol_version'):
        if type(capabilities_doc.get(key)) is not int:
            issues.append(f'/capabilities 缺少整数 {key}')
    caps = capabilities_doc.get('capabilities')
    if not isinstance(caps, dict):
        issues.append('/capabilities 缺少 capabilities 对象')
        return issues
    components = openapi_doc.get('components')
    schemas = components.get('schemas', {}) if isinstance(components, dict) else {}
    if not isinstance(schemas, dict) or not schemas:
        issues.append('OpenAPI 缺少 components.schemas')
        return issues
    for capability, requirement in CAPABILITY_SCHEMA_REQUIREMENTS.items():
        declared = caps.get(capability) == 1
        required_schemas = requirement['schemas']
        present = [name for name in required_schemas if name in schemas]
        missing = [name for name in required_schemas if name not in schemas]
        if declared and missing:
            issues.append(
                f'/capabilities 声明 {capability}=1，但 OpenAPI 缺少 Schema：'
                f'{"、".join(missing)}')
        for model, properties in requirement['schema_properties'].items():
            props = schemas.get(model, {}).get('properties', {})
            absent = [prop for prop in properties if prop not in props]
            if declared and not missing and absent:
                issues.append(
                    f'/capabilities 声明 {capability}=1，但 {model} 未开放字段：'
                    f'{"、".join(absent)}')
        if present and not declared:
            issues.append(
                f'OpenAPI 已包含 {"、".join(present)}，但 /capabilities 未声明 {capability}，'
                '客户端无法协商该字段扩展')
    return issues
