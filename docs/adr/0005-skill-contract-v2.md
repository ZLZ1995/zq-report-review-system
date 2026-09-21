# ADR 0005：Skill Contract v2

- 状态：已接受（G05 实施）
- 日期：2026-09-18

## 背景

当前契约（`skill_contracts.py` + `builtin_contracts/*.json`）含：id、version、purpose、source_extensions、required/optional roles、outputs、modify_originals、locked_template。工具层有 `tool_contracts.py`（每工具的验收门禁、输入模式）。安装层有哈希、路径穿越、大小、依赖检查和"不覆盖内置 ID"。缺口：无正反例、无 when_to_use/when_not_to_use、无网络/资源预算、无来源信任层级、无迁移兼容声明、无 Skill 评估集。

## 决定

1. 扩展机读契约 v2：增加 source/trust_level、when_to_use/when_not_to_use、positive/negative_examples、input_roles、allowed_tools、network_policy、template_locks、resource_locks、model_policy/token_budget、acceptance_gates、feedback_schema、compatibility/migration。
2. 来源优先级：官方锁定/managed > 官方签名更新 > 项目 > 用户外部 > 远程临时能力；同 ID 冲突不得静默覆盖，锁定模板只能由可信官方版本更新。
3. 补齐 12 项后台基础能力（material-classifier、turn-scope-resolver、office-runtime-preflight、document-evidence-indexer、spreadsheet-formula-auditor、document-layout-verifier、artifact-integrity-verifier、task-reconciliation、provider-diagnostics、browser-receipt-verifier、memory-curator、skill-lint-and-eval）；不恢复手动 Skill 切换。
4. 兼容 `.agents/skills/` 开放目录的发现，但信任层级不变。

## 替代方案

- 维持二分法（内置/外部）：拒绝，无法表达签名更新与项目级来源。
- 契约只放 SKILL.md 散文：拒绝，路由与治理需要机读字段。

## 后果

- `SkillContract` schema 升级需版本字段与旧契约读取兼容。
- 现有 6 个内置 Skill 与 2 个新本地 Skill 都要补齐 v2 字段与正反例。
- `skill_installation` 的"禁止覆盖内置 ID"扩展为完整信任层级裁决。

## 验收

- G05：每个正式 Skill 有正反例、输入角色和最小验收集；同 ID 冲突不静默覆盖；外部 ZIP 无法路径穿越/执行未知脚本/读取平台密钥；自然语言路由覆盖两项新 Skill 与既有业务 Skill。
