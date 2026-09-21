"""Versioned local harness records. Validation never grants execution authority."""
from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IdentityText = Annotated[str, Field(min_length=1, max_length=128, pattern=r'^\S+$')]
Positive = Annotated[int, Field(gt=0, strict=True)]


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_version: Literal[1] = 1

    @field_validator('schema_version', mode='before')
    @classmethod
    def strict_version(cls, value):
        if type(value) is not int:
            raise ValueError('schema_version must be an integer')
        return value


class TaskIdentity(Contract):
    owner: IdentityText
    project_id: IdentityText
    session_id: IdentityText
    task_id: IdentityText
    request_id: IdentityText


class ScopedRecord(Contract):
    identity: TaskIdentity
    step_id: IdentityText


class PlanStep(ScopedRecord):
    tool: IdentityText
    dependencies: list[IdentityText] = Field(default_factory=list, max_length=100)
    acceptance_gates: list[IdentityText] = Field(default_factory=list, max_length=50)

    @model_validator(mode='after')
    def dependencies_are_unique(self):
        if len(set(self.dependencies)) != len(self.dependencies) or self.step_id in self.dependencies:
            raise ValueError('Invalid plan dependencies')
        return self


class ToolCall(ScopedRecord):
    tool: IdentityText
    arguments: dict = Field(default_factory=dict)
    permission_ids: list[IdentityText] = Field(default_factory=list, max_length=100)

    @field_validator('arguments')
    @classmethod
    def bounded_json(cls, value):
        try:
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError, RecursionError) as exc:
            raise ValueError('Tool arguments must be bounded JSON') from exc
        if len(encoded.encode('utf-8')) > 32000:
            raise ValueError('Tool arguments exceed limit')
        return value


class TaskEvent(ScopedRecord):
    sequence: Positive
    kind: Literal['progress', 'output_delta', 'artifact', 'cancelled', 'failed', 'succeeded']
    text: str = Field(default='', max_length=16000)


class Artifact(ScopedRecord):
    artifact_id: IdentityText
    file_name: str = Field(min_length=1, max_length=255)
    sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    size_bytes: int = Field(ge=0, strict=True)
    # Paths are resolved locally by the artifact registry, not accepted from LLMs.


class PermissionGrant(Contract):
    identity: TaskIdentity
    action: Literal['read_selected', 'call_model', 'create_copy', 'browser_read', 'browser_upload']
    object_ids: list[IdentityText] = Field(min_length=1, max_length=100)
    confirmation_id: IdentityText
    task_revision: Positive
    # Only a trusted permission service may issue/register this record. A model's
    # correctly shaped JSON is still untrusted and cannot authorize its own call.


class PublicError(ScopedRecord):
    code: Literal['network_unavailable', 'protocol_incompatible', 'permission_denied',
                  'input_changed', 'output_invalid', 'cancelled', 'internal_error']

    @property
    def message(self):
        return {
            'network_unavailable': '网络连接失败，请检查连接后查询任务状态。',
            'protocol_incompatible': '服务端协议不兼容，请联系管理员。',
            'permission_denied': '当前操作没有相应授权。',
            'input_changed': '输入文件或任务范围已变化，请重新确认。',
            'output_invalid': '输出未通过校验，未作为正式成果交付。',
            'cancelled': '任务已取消，已提交的远程操作需核对状态。',
            'internal_error': '任务执行失败，请凭任务编号查询诊断记录。',
        }[self.code]
