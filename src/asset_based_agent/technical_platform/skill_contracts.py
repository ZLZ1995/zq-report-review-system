"""Platform capability sidecars; business Skill rules and templates stay unchanged."""
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from ..agent_contracts import Identifier, ShortText, Versioned
from .skills import BUILTINS


class SkillContract(Versioned):
    id: Identifier
    version: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    purpose: ShortText
    source_extensions: list[Literal['.docx', '.xlsx', '.xlsm', '.pdf', '.xls', '.json']] = Field(min_length=1)
    required_roles: list[Identifier] = Field(max_length=20)
    optional_roles: list[Identifier] = Field(max_length=20)
    outputs: list[Identifier] = Field(min_length=1, max_length=20)
    acceptance_gates: list[Identifier] = Field(min_length=1, max_length=20)
    followups: list[Identifier] = Field(max_length=20)
    environment: list[ShortText] = Field(max_length=10)
    limitations: list[ShortText] = Field(max_length=10)
    requires_model: bool
    creates_copy: bool
    locked_template: bool
    modify_originals: Literal[False]

    @model_validator(mode='after')
    def distinct_roles(self):
        roles = self.required_roles + self.optional_roles
        if len(set(roles)) != len(roles):
            raise ValueError('Duplicate input roles')
        if self.locked_template and not self.creates_copy:
            raise ValueError('Locked template requires a copy generator')
        return self


def builtin_contracts():
    root = Path(__file__).with_name('builtin_contracts')
    contracts = {}
    for name in ('report_review', 'detail_workbook', 'company_history', 'preflight',
                 'financial_brief', 'office_workflow_to_skill'):
        item = SkillContract.model_validate_json((root / (name + '.json')).read_text('utf-8'))
        if item.id in contracts:
            raise ValueError('Duplicate builtin contract')
        contracts[item.id] = item
    if {s.id: s.version for s in BUILTINS} != {k: v.version for k, v in contracts.items()}:
        raise ValueError('Builtin contract and adapter versions differ')
    return contracts
