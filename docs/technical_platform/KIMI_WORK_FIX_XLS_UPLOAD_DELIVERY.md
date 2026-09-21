# KIMI_WORK_FIX_XLS_UPLOAD 最终交付（K09）

> 工作文档：`KIMI_WORK_FIX_XLS_UPLOAD_AND_CLARIFICATION_RESUME.md`
> 施工仓库：`D:\ZQ-Acceptance\local-feature-checkout`，分支 `codex/local-platform-feature-update`
> 过程账本：`KIMI_WORK_FIX_XLS_UPLOAD_LEDGER.md`（K00—K08 逐阶段记录）

## 1. 根因与责任边界

用户报告的".xls 上传失败 + 补充资料后理解异常"体验问题，根因分四层：

1. **接入层**：文件选择器与拖拽白名单不含 `.xls`，生成管线只认 `.xlsx`，A8T 真实 BS/PL（`.xls`）静默丢失。
2. **理解层**：Agent 任务理解前没有本地结构化资料证据，同主体多期间（2023—2026.7 共 8 份 TB/TBD）无法确定性消歧，只能反复问用户。
3. **错误分类层**：服务端响应 Schema 校验失败等异常被宽泛 `except` 吞掉后统一误报为"连接及服务端状态"，掩盖真实原因。
4. **管线解析层（本轮真实复测新发现）**：序时账 xlsx 加载器只探测金蝶式表头，Oracle ERP 导出的序时账识别失败后静默回退固定列字母，导致科目代码/客商全部错位或为空，下游序时账证据链整体失效；写入侧与复核侧对"序时账严格候选""TB 客商解析""业务描述规范化"三套规则各自为政，产生成对的 journal_unmatched 与 source_mismatch。

责任边界：第 1—3 层为平台缺陷（本仓库）；第 4 层为估值明细 Skill 管线对真实 ERP 导出格式的适配缺陷（本仓库 `.codex/skills/`）；服务端 `material_evidence` 能力声明已加，未部署时客户端自动降级为旧式请求，不阻断。资料本身的证据缺口（无银行对账单逐户明细、预收账款客商为 ERP 占位词）属于业务资料边界，如实列示为 needs_materials，不伪造通过。

## 2. 逐文件改动摘要

### 平台（src/asset_based_agent/）

| 文件 | 改动 |
|---|---|
| `technical_platform/app.py` | 文件选择器/拖拽白名单加入 `.xls` |
| `technical_platform/builtin_contracts/detail_workbook.json` | `source_extensions` → `[".xlsx", ".xls"]` |
| `technical_platform/xls_support.py`（新） | `.xls→.xlsx` 运行目录内转换（xlrd 读值、类型还原、隐藏表跳过并记录）、`xls_header_values` |
| `technical_platform/generation.py` | `.xls` 输入统一临时转换到 `converted/`，写 `xls_conversion_report.json`；原件 ID/哈希不变 |
| `technical_platform/material_summary.py`（新） | 理解前本地受限结构摘要（类型/主体/期间/可见表/表头证据/警告）；隐藏表不读；区间期间 `2026-01-2026-07` 识别；不含绝对路径/公式 |
| `technical_platform/material_analysis.py` | TB/TBD 多候选按表内主体+期间自动选最新；较早期间进 `reference_artifact_ids`（历史参考，不进对比报表）；TB/TBD 配对核验；追问仅限真实冲突 |
| `agent_contracts.py` + 服务端 `compat_agent_contracts.py` | 新增 `MaterialEvidence` + `EvidenceRef.evidence`（可选，旧请求兼容） |
| `technical_platform/agent_controller.py` | prepare 阶段为选中文件附本地摘要 |
| `report_review_server/services/remote_auth_service.py` | 错误分层：`error_code`/`http_status`、`RequestSchemaError`、`ResponseSchemaError`；`material_evidence` 能力门控降级 |
| `report_review_server/api.py` | /capabilities 声明 `material_evidence` |
| `report_review_server/prompts/task_understanding.txt` | evidence 使用规则 |
| `technical_platform/routing.py` | 理解与生成 Worker 十层错误分类；理解失败明示"Skill 尚未启动"；未知异常不再冒充网络故障 |
| `technical_platform/diagnostics.py` | `log_worker_failure` 脱敏诊断日志（追加式，未覆盖既有内容） |
| `technical_platform/compound_task.py` | 计划文件版本比较限定三键，兼容 evidence 字段 |

### Skill 管线（.codex/skills/valuation-detail-workbook-fill/scripts/）

| 文件 | 改动 |
|---|---|
| `cover_metadata.py` | 公司识别支持 `公司=CODE (全称)`、`公司: CODE - 全称`；`本期/期间：YYYY-MM` 按月末推导 |
| `run_detail_workbook_pipeline.py` | ① 单边资产负债表布局检测 + 预提费用并入其他流动负债；② 锁定模板明细写入跳过非确认单元格并记录 `_written_cells`；③ stage2 直写块公式保护 + 其他流动负债（预提费用）BS 证据行；④ 序时账 xlsx 加载器新增 Oracle ERP 表头探测（`会计科目代码`/`本币借贷发生额`/`供应商名称`/`往来描述`），ERP 双客商列按科目语义择一（内部往来取往来描述、其余取供应商名称、禁用词兜底）；⑤ `strict_journal_candidates` 严格候选规则共享化，支持本行 tb_code 接纳重分类科目；⑥ `resolve_tb_counterparty` 共享 TB 客商解析（有效名保留、禁用名取序时账最大单笔客商、例外名单）；⑦ 待查资金入账 2241990000 保留净额负数；⑧ 语义占位门禁小额容限（≤1000 且有占位行）推广到全部必填明细表 |
| `post_generation_review.py` | 复核侧与写入侧统一：严格候选委托 pipeline 共享实现并传本行 tb_code；expected 键经 `resolve_tb_counterparty`；业务描述规范化补传 account_name；只比对 `_written_cells` 实际写入格；聚合表（银行/税费）豁免逐格显式证据映射；例外名单客商跳过序时账匹配改记 needs_materials |

### 测试（tests/，全部修复前失败、修复后通过）

`test_xls_upload.py`(11)、`test_material_summary.py`(12)、`test_understanding_evidence.py`(6)、`test_understanding_evidence_client.py`(2)、`test_material_evidence.py`(3)、`test_material_auto_disambiguation.py`(9)、`test_clarification_resume.py`、`test_error_classification.py`(15)、`test_journal_erp_header.py`(6)、`test_journal_candidate_unification.py`(4)、`test_a8t_validation_consistency.py`(9)、`test_balance_sheet_single_sided.py`(3)、`test_cover_metadata_a8t.py`(3)、`test_locked_detail_write.py`(2)

## 3. 数据契约变化

- `detail_workbook.json`：`source_extensions` 增加 `.xls`（向后兼容，`.xlsx` 不变）。
- `MaterialEvidence`/`EvidenceRef.evidence`：可选新增字段；空值序列化自动剔除，旧字节流与旧服务端兼容；服务端未声明能力时客户端自动降级。
- `MaterialResolution.reference_artifact_ids`：末尾新增字段，位置构造兼容；历史参考不再误入 `comparison_artifact_ids`。
- 管线内部：序时账条目 `vendor_name`/`counterparty_desc` 对 ERP 布局为择一后的同一值（不变式恢复）；明细写入记录新增 `_written_cells`（可选，复核对缺省记录保持旧行为）。
- 行为变化（已测试固定）：语义占位门禁小额容限推广；聚合表（银行存款/应交税费）豁免逐格显式证据映射（其总额仍受分类汇总链与专项校验约束）；待查资金入账等例外名单客商不再要求序时账匹配，改列 needs_materials。

## 4. 数据库迁移及兼容性说明

无。`state.sqlite` 结构未变；消歧快照为 JSON 序列化，新增字段末尾追加，旧记录可读。

## 5. 验证命令与结果

| 命令 | 结果 |
|---|---|
| `pytest tests/technical_platform/test_xls_upload.py` | 11 passed |
| `pytest tests/technical_platform/test_material_summary.py tests/technical_platform/test_understanding_evidence.py tests/technical_platform/test_understanding_evidence_client.py tests/report_review_server/test_material_evidence.py` | 23 passed |
| `pytest tests/technical_platform/test_material_auto_disambiguation.py` | 9 passed |
| `pytest tests/technical_platform/test_clarification_resume.py` | passed（K05 复现 + K06 固定） |
| `pytest tests/technical_platform/test_error_classification.py` | 15 passed |
| `pytest tests/technical_platform/test_journal_erp_header.py test_journal_candidate_unification.py test_a8t_validation_consistency.py test_balance_sheet_single_sided.py test_cover_metadata_a8t.py test_locked_detail_write.py` | 25 passed |
| 全量：`pytest tests/technical_platform tests/report_review_app tests/report_review_server`（offscreen，basetemp 独立目录） | **1774 passed, 1 skipped**（9m40s，EXIT=0） |
| A8T 真实只读复测 `k08_real_run.py`（ReplayProvider，无模型计费） | **K08 REAL RUN OK** |

## 6. A8T 真实文件复测证据

- 11 个真实文件全部注册（含 2 个原始 `.xls`），注册后逐文件表内摘要分类；主体识别 A8T；自动选中 2026-07 最新 TB/TBD/BS；2023—2025 六份自动列为历史参考；无提问直接 resolved。
- 单次生成任务（run state: succeeded），最终产出评估明细表主成果（531,535 字节）；用户可见成果仅 1 个：阿里云飞天（北京）云计算有限公司评估明细表（2026-07-31）.xlsx；内部校验 JSON 不列示。
- 关键勾稽抽查（发布件）：货币资金 726.52、预付账款 10,600.00、其他应付款明细合计 14,043,611.33 = BS（含待查资金入账 -32,537.99 净额行）、其他流动负债 109,884.54（预提费用行）、应付账款拆分为 安永 10,651.61 + 平安保险 6,105.90（序时账证据解析自 TB 占位词）。
- 序时账解析：真实 TBD 2,239 条干净分录，1124050000+浙江天猫 65 行，0 垃圾行。
- 声明的证据边界（不阻塞、如实列示 needs_materials）：银行存款无逐户对账单明细；预收账款 -0.32 客商为 ERP 占位词。
- 工件位置：会话工作区 `k08-real-run/`（run.log、done.txt=K08 REAL RUN OK、runs/…/output/ 全套内部校验 JSON）。

## 7. 原件哈希校验

复测前后 11 个原件 SHA256 逐一比对一致（脚本内断言，日志 `all 11 original hashes unchanged`）；`.xls` 转换只写运行目录 `converted/`，不写回原件；锁定模板 SHA256 与 template.lock.json 一致。

## 8. 计费幂等检查

- 复测全程 ReplayProvider 回放，零模型调用、零计费。
- `test_resume_after_clarification_skips_model_and_completes` 固定：澄清恢复不重复调用模型（不重复扣费）。
- `test_file_metadata_change_invalidates_result_without_reading_source` 固定：飞行中旧请求因范围变化失效，不污染新范围（迟到结果保护）。
- 复测确认单次运行、单次发布，无重复 run。

## 9. 剩余风险与阻塞

1. 服务端 `material_evidence` 能力需部署后方生效；未部署时客户端自动降级旧式请求（功能可用，理解精度退回文件名时代）。
2. PL/CF 仅作参考证据，非生成管线输入（PL.xls 不转换，摘要经 xlrd 读取）；利润表不参与本轮明细表生成勾稽。
3. Excel/WPS 真实打开验证无本机自动化手段：已以 openpyxl/zip 结构校验 + 公式 fullCalcOnLoad 代替，未做真实 Office 打开确认。
4. 待查资金入账行的发生日期/业务内容沿用项目既有"见明细"映射逻辑（本项目既定行为）；复核侧已改记 needs_materials，提示需银行流水另行佐证。
5. 仓库根级 `tests/` 下 3 个既有收集错误（缺 `test_detail_workbook_pipeline_guards` 模块）为历史遗留，不在标准套件与本轮范围内。
6. 本交付仅本地提交，未推送 GitHub、未更新 Release/Zeabur、未替换正式 EXE（按授权边界）。

## 10. 回滚步骤

```bash
cd D:\ZQ-Acceptance\local-feature-checkout
git reset --hard 5951eb0   # K00 基线；或逐提交 git revert 7a6b42d 2135fb4 1c8523d 29d34bd a742b11 04f36a4
```

无数据库迁移、无远程推送、无外部状态变更，回滚即完全复原。

## 11. 分支、HEAD 与工作树状态

- 分支：`codex/local-platform-feature-update`
- HEAD：`7a6b42d`（K08）+ 账本脱敏提交（见 git log 最新一条）
- 提交链：`04f36a4`(K02) → `a742b11`(K03) → `29d34bd`(K04) → `1c8523d`(K05/K06) → `2135fb4`(K07) → `7a6b42d`(K08) → 账本脱敏
- 工作树：交付文档提交后干净；远程分支不存在本地分支对应 ref，确认零推送
