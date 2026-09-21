"""Skill Contract v2: machine-readable, routable, governable capabilities.

Source priority: 官方锁定/managed > 官方签名更新 > 项目 > 用户外部 > 远程临时。
同 ID 同优先级但内容不同是冲突，必须显式处理，绝不静默覆盖。
锁定模板只能由可信官方来源更新。基础能力是后台能力，不恢复手动切换。
"""
from __future__ import annotations

import json
from hashlib import sha256
from typing import Literal

from pydantic import Field, field_validator

from ..agent_contracts import Identifier, Record, ShortText

SkillSource = Literal['official_locked', 'managed', 'official_signed',
                      'project', 'user_external', 'remote_temp']
TrustLevel = Literal['locked', 'high', 'standard', 'low', 'ephemeral']

SOURCE_PRIORITY = {'official_locked': 50, 'managed': 40, 'official_signed': 30,
                   'project': 20, 'user_external': 10, 'remote_temp': 0}
_TEMPLATE_TRUSTED_SOURCES = frozenset({'official_locked', 'managed'})


class SkillContractV2(Record):
    schema_version: Literal[1] = 1
    id: Identifier
    name: str = Field(min_length=1, max_length=200)
    version: str = Field(pattern=r'^\d+\.\d+\.\d+$')
    source: SkillSource
    trust_level: TrustLevel
    description: ShortText
    when_to_use: ShortText
    when_not_to_use: ShortText
    positive_examples: tuple[ShortText, ...] = Field(min_length=1, max_length=20)
    negative_examples: tuple[ShortText, ...] = Field(min_length=1, max_length=20)
    input_roles: tuple[Identifier, ...] = Field(min_length=1, max_length=20)
    required_inputs: tuple[Identifier, ...] = ()
    optional_inputs: tuple[Identifier, ...] = ()
    supported_extensions: tuple[str, ...] = ()
    output_types: tuple[str, ...] = Field(min_length=1, max_length=20)
    allowed_tools: tuple[Identifier, ...] = ()
    network_policy: Literal['none', 'allowlist', 'session'] = 'none'
    modifies_originals: Literal[False] = False
    template_locks: tuple[str, ...] = ()
    resource_locks: tuple[Identifier, ...] = ()
    model_policy: Literal['none', 'required', 'optional'] = 'optional'
    token_budget: int = Field(default=4000, ge=0, le=200000)
    acceptance_gates: tuple[Identifier, ...] = Field(min_length=1, max_length=20)
    feedback_schema: str = Field(min_length=1, max_length=64)
    compatibility: str = Field(min_length=1, max_length=64)
    migration: str | None = None

    @field_validator('schema_version', mode='before')
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError('Invalid schema version')
        return value


class ConflictReport(Record):
    overridden: tuple[SkillSource, ...] = ()


def _content_hash(contract: SkillContractV2) -> str:
    payload = json.dumps(contract.model_dump(exclude={'source', 'trust_level'}),
                         sort_keys=True, ensure_ascii=False, allow_nan=False)
    return sha256(payload.encode('utf-8')).hexdigest()


def resolve_conflicts(contracts) -> tuple[dict[str, SkillContractV2], ConflictReport]:
    """Same-id resolution: higher source priority wins; equal priority with
    different content raises instead of silently overwriting."""
    parsed = [SkillContractV2.model_validate(
        item.model_dump() if isinstance(item, SkillContractV2) else item)
        for item in contracts]
    winners: dict[str, SkillContractV2] = {}
    overridden: list[SkillSource] = []
    for contract in sorted(parsed, key=lambda item: (-SOURCE_PRIORITY[item.source],
                                                     item.id, item.version)):
        current = winners.get(contract.id)
        if current is None:
            winners[contract.id] = contract
            continue
        if SOURCE_PRIORITY[current.source] > SOURCE_PRIORITY[contract.source]:
            overridden.append(contract.source)
            continue
        if _content_hash(current) != _content_hash(contract):
            raise ValueError(f'Skill {contract.id} 同优先级来源内容冲突，需显式处理')
    return winners, ConflictReport(overridden=tuple(overridden))


def assert_template_update_allowed(current: SkillContractV2, candidate: SkillContractV2):
    """Locked templates accept updates only from trusted official sources."""
    current = SkillContractV2.model_validate(current.model_dump())
    candidate = SkillContractV2.model_validate(candidate.model_dump())
    if candidate.template_locks and candidate.source not in _TEMPLATE_TRUSTED_SOURCES:
        raise PermissionError('锁定模板只能由可信官方版本更新')


def _foundation(identity, name, description, when_to_use, when_not_to_use,
                positive, negative, roles, required, optional, outputs, gates,
                extensions=(), template_locks=()) -> SkillContractV2:
    return SkillContractV2(
        id=identity, name=name, version='1.0.0', source='official_locked',
        trust_level='locked', description=description, when_to_use=when_to_use,
        when_not_to_use=when_not_to_use, positive_examples=positive,
        negative_examples=negative, input_roles=roles, required_inputs=required,
        optional_inputs=optional, supported_extensions=extensions,
        output_types=outputs, allowed_tools=('read_selected_files',),
        network_policy='none', modifies_originals=False, model_policy='optional',
        template_locks=template_locks,
        acceptance_gates=gates, feedback_schema='skill-feedback-v1',
        compatibility='>=1.0.0', migration=None)


def foundation_capabilities() -> tuple[SkillContractV2, ...]:
    """The twelve backstage foundation capabilities (never a manual selector)."""
    return (
        _foundation('material-classifier', '资料分类', '把本轮资料分类为审核对象或参考',
                    '每轮执行前的资料归类', '纯问答',
                    ('把这几份资料分一下类',), ('随便聊聊',),
                    ('target', 'reference'), ('target',), ('reference',),
                    ('classification.json',), ('scope-consistency',),
                    ('.docx', '.xlsx', '.pdf')),
        _foundation('turn-scope-resolver', '本轮范围解析', '解析本轮资料范围与排除项',
                    '每轮提交后', '无文件且纯问答',
                    ('只审这份，不看那份',), ('今天天气怎么样',),
                    ('target',), ('target',), ('reference',),
                    ('scope.json',), ('envelope-consistency',)),
        _foundation('office-runtime-preflight', 'Office 运行预检', '检查 Office/WPS 可用性',
                    'Office 任务开始前', '纯浏览器任务',
                    ('先看看本机Office能不能用',), ('打开网页看看',),
                    ('runtime',), ('runtime',), (),
                    ('preflight.json',), ('runtime-probe',)),
        _foundation('document-evidence-indexer', '文档证据索引', '为文档建立证据片段索引',
                    '审核类任务取证', '纯生成任务',
                    ('把报告里的证据标出来',), ('随便写点什么',),
                    ('target', 'reference'), ('target',), ('reference',),
                    ('evidence-index.json',), ('hidden-sheet-filter',),
                    ('.docx', '.xlsx', '.pdf')),
        _foundation('spreadsheet-formula-auditor', '公式审计', '审计工作表公式与链接',
                    '表格成果校验', '纯文本问答',
                    ('检查一下公式有没有问题',), ('讲个故事',),
                    ('target',), ('target',), ('reference',),
                    ('formula-audit.json',), ('formula-integrity',),
                    ('.xlsx', '.xlsm')),
        _foundation('document-layout-verifier', '版式校验', '校验文档版式与字体字号',
                    '成果文档交付前', '数据核对任务',
                    ('看看排版有没有跑偏',), ('算一下总数',),
                    ('artifact',), ('artifact',), (),
                    ('layout-report.json',), ('layout-consistency',),
                    ('.docx',)),
        _foundation('artifact-integrity-verifier', '成果完整性校验', '校验成果哈希与来源',
                    '任何成果交付前', '对话问答',
                    ('确认下生成的文件没被改动',), ('闲聊',),
                    ('artifact',), ('artifact',), (),
                    ('integrity.json',), ('hash-match',)),
        _foundation('task-reconciliation', '任务对账', '对账未知状态的远程任务',
                    '任务状态未知时', '本地已确认完成的任务',
                    ('刚才那个任务到底扣没扣费',), ('新任务开始',),
                    ('receipt',), ('receipt',), (),
                    ('reconciliation.json',), ('no-double-charge',)),
        _foundation('provider-diagnostics', '渠道诊断', '诊断模型渠道状态',
                    '模型调用失败时', '正常任务执行中',
                    ('模型是不是挂了',), ('帮我审报告',),
                    ('runtime',), ('runtime',), (),
                    ('diagnostics.json',), ('no-secret-leak',)),
        _foundation('browser-receipt-verifier', '浏览器回执校验', '校验浏览器任务回执',
                    '浏览器任务完成后', '本地文档任务',
                    ('核对一下OA回执',), ('审一下合同',),
                    ('receipt',), ('receipt',), (),
                    ('receipt-check.json',), ('origin-binding',)),
        _foundation('memory-curator', '记忆治理', '治理记忆候选的生命周期',
                    '主回复结束后', '任务执行中',
                    ('刚才说的偏好记下来',), ('马上执行任务',),
                    ('candidate',), ('candidate',), (),
                    ('memory-plan.json',), ('sensitive-scan',)),
        _foundation('skill-lint-and-eval', 'Skill 质检', '校验 Skill 契约与评估',
                    'Skill 安装或更新前', '业务执行',
                    ('检查一下这个新技能包',), ('直接运行脚本',),
                    ('candidate',), ('candidate',), (),
                    ('skill-lint.json',), ('contract-validity',)),
    )


def business_skill_descriptors() -> tuple[SkillContractV2, ...]:
    """v2 descriptors for the existing business adapters (routing metadata)."""
    return (
        _foundation('report.review', '报告审核', '审核 Word/Excel 报告并出具意见',
                    '需要审核报告或表格时', '生成类任务',
                    ('帮我审一下这份报告', '核对明细表数据'),
                    ('帮我写一份报告', '随便聊聊'),
                    ('target', 'reference'), ('target',), ('reference',),
                    ('review-report.docx', 'annotation-copy.docx'),
                    ('readonly-originals', 'hidden-sheet-filter'),
                    ('.docx', '.xlsx', '.xlsm')),
        _foundation('valuation-detail-workbook-fill', '评估明细表填写',
                    '按锁定模板填写评估明细表',
                    '需要填写评估明细表时', '审核类任务',
                    ('按模板填评估明细表',), ('帮我审合同',),
                    ('target',), ('target',), ('reference',),
                    ('valuation-detail.xlsx',),
                    ('locked-template', 'formula-integrity', 'wan-yuan-unit'),
                    ('.xlsx',), ('template.xlsx',)),        _foundation('gongshang-change-history-docx', '工商沿革生成',
                    '由工商信息生成历史沿革文档',
                    '需要工商沿革文档时', '表格核对',
                    ('把工商信息做成沿革文档',), ('审一下报告',),
                    ('target',), ('target',), (),
                    ('change-history.docx',),
                    ('font-layout-lock',), ('.xlsx',)),
        _foundation('financial-brief-docx', '财务简报生成', '由财务数据生成简报',
                    '需要财务简报时', '审核类任务',
                    ('用财务数据出一份简报',), ('填明细表',),
                    ('target',), ('target',), (),
                    ('financial-brief.docx',), ('readonly-originals',),
                    ('.xlsx',)),
        _foundation('office-workflow-to-skill', '办公流程转技能',
                    '把示范过的办公流程固化为技能包',
                    '用户要求沉淀流程时', '一次性任务',
                    ('把刚才的流程做成技能',), ('审一下报告',),
                    ('recording',), ('recording',), (),
                    ('skill-package.zip',), ('contract-validity',)),
    )
