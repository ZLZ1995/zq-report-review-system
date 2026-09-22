"""S4-03 Tool Schema 限制：大小/深度/properties 数/required 对应/关键字白名单（先红后绿）。"""
from __future__ import annotations

import pytest

from asset_based_agent.report_review_server.services.agent_completion_service import (
    validate_tool_schemas,
)
from asset_based_agent.report_review_server.services.auth_service import (
    ServiceError,
)


def _tool(schema):
    return [{'name': 't', 'input_schema': schema}]


def _invalid(schema):
    with pytest.raises(ServiceError) as excinfo:
        validate_tool_schemas(_tool(schema))
    assert excinfo.value.code == 'invalid_tool_schema'
    assert excinfo.value.status_code == 400


def test_schema_size_limit():
    _invalid({'type': 'object', 'properties': {
        'a': {'type': 'string', 'description': 'x' * 20000}}})


def test_schema_depth_limit():
    node = {'type': 'string'}
    for _ in range(20):
        node = {'type': 'object', 'properties': {'n': node}}
    _invalid(node)


def test_properties_count_limit():
    _invalid({'type': 'object', 'properties': {
        f'p{i}': {'type': 'string'} for i in range(129)}})


def test_total_properties_budget_limit():
    """单对象不超 128，但整树 properties 总数同样受限（防分摊绕过）。"""
    children = {f'c{i}': {'type': 'object', 'properties': {
        f'p{j}': {'type': 'string'} for j in range(100)}} for i in range(8)}
    _invalid({'type': 'object', 'properties': children})


def test_required_must_reference_declared_property():
    _invalid({'type': 'object',
              'properties': {'a': {'type': 'string'}},
              'required': ['b']})


def test_unsupported_keywords_rejected():
    _invalid({'$ref': '#/definitions/x'})
    _invalid({'$defs': {'x': {'type': 'string'}},
              'type': 'object'})
    _invalid({'type': 'object',
              'patternProperties': {'^x': {'type': 'string'}}})


def test_recursive_ref_bomb_rejected():
    """$ref 自引用递归爆炸：$ref 本身即被拒。"""
    _invalid({'$ref': '#'})


def test_nested_nodes_also_checked():
    """嵌套节点的非法关键字/深度同样拒绝，不得只在顶层校验。"""
    _invalid({'type': 'object', 'properties': {
        'a': {'type': 'object', 'properties': {
            'b': {'$ref': '#/definitions/x'}}}}})


def test_valid_nested_schema_accepted():
    validate_tool_schemas(_tool({
        'type': 'object',
        'properties': {
            'query': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100},
            'tags': {'type': 'array',
                     'items': {'type': 'string'},
                     'maxItems': 10, 'uniqueItems': True},
            'mode': {'enum': ['a', 'b']},
            'filter': {'anyOf': [{'type': 'string'}, {'type': 'null'}],
                       'default': None},
        },
        'required': ['query'],
        'additionalProperties': False,
    }))
