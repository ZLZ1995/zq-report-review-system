# Kimi Work 执行账本：XLS 接入、资料自动判断与补充文件续接（K00—K09）

> 工作文档：`D:/1/1/ai-excel-agent/docs/technical_platform/KIMI_WORK_FIX_XLS_UPLOAD_AND_CLARIFICATION_RESUME.md`
> 施工仓库：`D:\ZQ-Acceptance\local-feature-checkout`（文档中 `D:/1/1/ai-excel-agent` 写法与前几轮相同，为模板残留；权威工作树以交接文档与既有账本为准，`D:/1/1` 有 863 个未提交用户改动，不施工）

## K00：基线与现场保护

- 分支：`codex/local-platform-feature-update`
- HEAD：`5951eb0 docs: record candidate EXE build 20260920-0615`
- `git status --short`：干净
- Python 环境：`D:\1\1\ai-excel-agent\.venv\Scripts\python.exe`（含 xlrd 2.0.2 / xlwt 1.3.0），`QT_QPA_PLATFORM=offscreen`，PYTHONPATH=src
- 测试入口：`pytest tests/technical_platform tests/report_review_app tests/report_review_server -q --basetemp=D:/ZQ-Acceptance/tmp-pytest-basetemp -p no:cacheprovider`（根级 tests/test_detail_*.py 三个既有收集错误，不跑全目录）
- 当前基线：1687 passed / 1 skipped / 0 failed（上一轮末态）
- 已读：AGENTS.md（D:/1/1 HEAD 版）、agent-diagnose-runtime/SKILL.md、agent-tdd-fix/SKILL.md、valuation-detail-workbook-fill/SKILL.md、多期间路由工作文档（上轮已执行）
- 业务文件未复制进仓库；初始 SHA256 记录于下方

### 已确认代码事实（修复前）

1. **XLS 接入**：`app.py:1200` 文件选择器过滤器 `资料 (*.docx *.xlsx *.xlsm *.pdf *.json *.zip)` 无 `.xls`；`app.py:1237` `import_files` 白名单 `{.docx,.xlsx,.xlsm,.pdf,.json,.zip}` 无 `.xls`；拖拽（eventFilter → import_files）同一路径被拒绝。`skill_contracts.py:15` 契约 Literal 已含 `.xls`；`generation.py:30` INPUT_ROLES 中 trial_balance/balance_sheet/journal 已允许 `.xls`；`builtin_contracts/detail_workbook.json` `source_extensions` 仅 `[".xlsx"]`——契约层不一致属实。
2. **理解异常文案**：`routing.py:83-84` `UnderstandingWorker.run` 宽泛 `except Exception` → "任务理解未完成，请检查连接及服务端状态；未启动业务执行。"，与 1.3 节故障文案一致；真实异常被丢弃。
3. **追问根因**：`agent_controller.py:74` `EvidenceRef` 只携带 `id/name/sha256`，模型拿不到主体/期间/表头证据。
4. **xlrd 2.0.2 在 venv 可用**（仅读 .xls）；生成管线用 openpyxl 读 inputs，`.xls` 需在运行目录临时转换为 `.xlsx` 并记录转换报告。

### A8T 真实业务文件初始 SHA256（只读使用，不进仓库）

| 文件 | 字节 | SHA256（前 16 位） |
|---|---|---|
| 2023_TB.xlsx | 5,236 | 497bb3a346a476c3 |
| 2024_TB.xlsx | 10,341 | cd917a2b81863d97 |
| 2025_TB.xlsx | 13,362 | 947a92bd62c23ef6 |
| 2026.07_TB.xlsx | 18,391 | eb0c1830543f033a |
| 2023_TBD.xlsx | 54,980 | b50d80ecd52634a1 |
| 2024_TBD.xlsx | 397,676 | 121c94fb76f0fade |
| 2025_TBD.xlsx | 835,600 | 9a1460d4dcf54b9d |
| 2026.1-7_TBD.xlsx | 572,064 | 3c9a717d45ea611e |
| A8T-BS202607.xls | 111,104 | 97abda65854a8d8b |
| A8T-PL202607.xls | 104,448 | 8e563bbd0efa3e9f |
| A8T-CF202607.xlsx | 9,226 | 0b93185a1d1d6f92 |

位置：`D:\工作\2026.5.8A8T（封存）\` 下 `A8T-股权评估资料(1)\2、…科目汇总表`（TB×4）、`…\3、…序时账`（TBD×4）、`盖章邮寄资料-A8T\5.审计报告及基准日财务报表`（BS/PL 为 .xls，CF 为 .xlsx）。

（后续阶段陆续追加）

## K01：测试固定 .xls 接入缺陷

- 新测试 `tests/technical_platform/test_xls_upload.py`（11 个）：选择器/拖拽/混合批量/契约声明/拒绝不支持格式/两路径一致/哈希保真 + 转换与元数据读取
- 修复前：6 failed / 1 passed（选择器、拖拽、混合、契约、一致性、哈希全部因真实白名单缺陷失败）；补转换与元数据测试后 10 failed / 1 passed

## K02：统一 XLS 接入契约

- `app.py`：文件选择器过滤器与 `import_files` 白名单加入 `.xls`（拖拽同路径生效）
- `builtin_contracts/detail_workbook.json`：`source_extensions` → `[".xlsx", ".xls"]`（`skill_contracts.py` Literal 原本已含 `.xls`，无需改）
- 新模块 `xls_support.py`：`convert_xls_to_xlsx`（xlrd 读值 → openpyxl 写，日期/布尔类型还原，隐藏/veryHidden 工作表跳过并记录）、`xls_header_values`（可见表表头文本，日期单元格同时产出中文与 ISO 两种文本）
- `generation.py`：运行目录内 `.xls` 输入统一临时转换到 `converted/`，写 `xls_conversion_report.json`（工具、源/产出哈希、跳过的隐藏表）；原文件 ID/SHA256 不变，不写回原件
- `material_analysis.statement_metadata`：支持 `.xls`（经 xls_header_values），逻辑与 .xlsx 一致
- 转换失败给真实原因（xlrd 错误透传）；不要求用户手工转换
- 验证：`test_xls_upload.py` 11 passed；目标回归子集 96 passed（material/automatic routing/generation/understanding policy/export/delivery presentation）

## K03：Agent 理解前本地资料预识别

- 新模块 `material_summary.py`：`summarize_file` 产出受限结构摘要（format/readable/document_type/entity_name/period/可见表名/header_evidence/confidence/warnings）；`.xls` 经 xlrd、`.xlsx/.xlsm` 经 openpyxl，语义一致；隐藏/veryHidden 工作表一律不读不进摘要（只记数量）；仅年月期间按月末规则标准化并在 warnings 保留推导标识；摘要不含绝对路径/公式/二进制
- 类型识别：BS/PL/CF/TB/TBD 按表内标题与表头证据；主体识别支持 `公司=CODE (名称)`、`公司: CODE - 名称`、`编制单位：` 等真实格式；CF 空表头进入 warnings（主体/期间缺失）并降置信度
- 契约扩展：`agent_contracts.py` 与服务端 `compat_agent_contracts.py` 同步新增 `MaterialEvidence` + `EvidenceRef.evidence`（可选，旧请求兼容；evidence 为空时序列化自动剔除，旧字节流不变）；双份 Record 均 extra=forbid + 边界校验
- `agent_controller.prepare`：对选中工作簿文件附本地摘要（剥离与 EvidenceRef 重复的 artifact_id/name）
- `remote_auth_service.understand_task`：`material_evidence` 能力门控——服务端未声明时剔除摘要降级为旧式请求（不修改调用方 payload）；服务端 `api.py` /capabilities 声明 `material_evidence`
- 服务端 prompt `task_understanding.txt`：新增 evidence 使用规则（首要证据、readable=false/缺失警告按资料不足处理）
- `compound_task.py`：计划文件版本比较限定 id/name/sha256 三键，避免 evidence 字段破坏既有校验
- 测试：`test_material_summary.py`（11）+ `test_understanding_evidence.py`（6）+ `test_understanding_evidence_client.py`（2）+ `test_material_evidence.py`（3）；修复前 9 failed，修复后 22 passed；相关回归 92 passed（agent_controller/compound/routing/remote/server understanding/capabilities）

## K04：同主体多期间自动消歧

- `material_analysis.resolve_materials` 扩展 `trial_balance`/`journal` 多候选分支：经 `material_summary.summarize_file` 做表内主体/期间提取（TB 取 `期间: YYYY-MM`，TBD 取期间列最大值），同主体多期间确定性选最新；较早期间记入新字段 `reference_artifact_ids`（历史参考，**不进** `comparison_artifact_ids`，不会被当作 --financial-statement 对比报表）
- 追问仅限真实冲突：多主体 / 主体缺失 / 期间缺失 / 同主体同期间多版本；问题只点名无法推断的最小信息
- 新增 TB/TBD 配对核验：选中对的主体不一致或最新期间不一致 → waiting_user 精确提问；一致 → reasons 记录"自动配对"
- 文件名不覆盖表内证据（测试固定：名为 2023 的 TB 表内期间 2026-07 仍按 2026-07 处理）
- `MaterialResolution` 新增 `reference_artifact_ids`（置于末尾，位置构造兼容）；`resolution_snapshot` 同步输出
- 测试：`test_material_auto_disambiguation.py` 9 个（修复前 9 failed）；A8T 形态合成集（BS+TB×2+TBD×2）直接 resolved 无提问；既有 `test_material_multiperiod.py`/`test_material_analysis.py` 24 个回归全过；相关子集 45 passed

## K05：复现补充文件后的任务理解异常

- 复现测试 `test_clarification_resume.py`：完整两轮会话（9 资料 → ask → 同会话补 BS/PL → "本轮已补充资产负债表和利润表" → resume → plan），同步驱动 UnderstandingWorker，捕获 task_id/revision/新旧文件集合/问题上下文/请求Schema校验/异常类与阶段，诊断工件写入会话工作区 `k05_repro/diagnostics.json`（无 Token/路径/业务内容）
- **关键结论**：本地续接链路（controller.prepare resume + 新增文件进范围 + 第二轮理解 + complete）修复前即可走通——生产第二次故障不在本地状态/revision/文件作用域层，而在服务端响应或传输层被 `routing.py` 宽泛 `except Exception` 吞掉后误报为"连接及服务端状态"
- 固定误分类缺陷：`RemoteAuthenticationError`（服务端响应Schema校验失败）修复前显示"请检查连接及服务端状态"（测试修复前失败）

## K06：澄清会话文件增量续接

- 复现证明既有实现已满足：澄清状态持久化（question/context/revision）、第二轮请求携带原始目标+上轮问题+用户回答+当前勾选范围、新增文件可进范围且未被误判"文件变化"、第二轮成功后澄清关闭且下一轮开启新 task_id、客户端重启（重建 AgentController）后可恢复
- 无生产代码改动；既有 `test_file_metadata_change_invalidates_result_without_reading_source` 继续固定"飞行中旧请求因范围变化失效"，`test_resume_after_clarification_skips_model_and_completes` 固定澄清恢复不重复调用模型（不重复扣费）

## K07：错误分类与可观察性

- `remote_auth_service.py`：`RemoteAuthenticationError` 增加 `error_code`/`http_status`；新增 `RequestSchemaError`（请求本地Schema校验失败，未发送）与 `ResponseSchemaError`（服务端响应Schema校验失败）；`understand_task` 分层包装；`_raise_for_response` 对 422/409/5xx 保留 `http_<status>` 安全错误码；五个既有异常类带默认 error_code
- `routing.py` 两个 Worker：按 NetworkUnavailable/SessionRevoked/InsufficientBalance/BillingReconciliationRequired/ServerCapabilityUnavailable/请求Schema/响应Schema/安全服务端消息/本地校验/未分类内部错误 十层分类；理解阶段失败一律明示"Skill尚未启动，未创建业务任务"；未知异常不再冒充网络故障
- `diagnostics.py`（恢复原模块后追加）：`log_worker_failure` 记录 stage/异常类/error_code/http_status/request_id/task_id/revision + 脱敏 detail（Bearer/token/api-key/password/Cookie  scrub，限长300）；**教训记录**：本轮曾误覆盖既有 diagnostics 模块，被 test_billing_feedback 收集错误即时发现，已恢复原内容并改为追加
- 测试 `test_error_classification.py` 15 个（修复前 13 failed）：逐类断言文案、未分类不冒充网络、日志含 ids 且不含秘密、422/409/500 分码、RequestSchema/ResponseSchema 分层；K05 复现测试同步转绿；相关回归 79 passed

## K08：完整回归和 A8T 真实文件只读复测

复测方式：`k08_real_run.py`（ReplayProvider 确定性回放，不走模型计费）注册 A8T 真实 11 文件 → material_summary 表内证据分类 → resolve_materials 真实消歧 → execute_generation 完整 DETAIL 管线 → 验收矩阵。复测驱动管线修复共 9 项，全部测试先行。

**第一批（真实表结构适配）**

- `material_summary.py`：新增区间期间识别（真实 TBD row2 为 `期间：2026-01-2026-07` 区间形式，旧正则会把 `-2026` 误读为"日=20"）→ period_start=2026-01-01、period_end=2026-07-31，推导记入 warnings；测试并入 `test_material_summary.py::test_journal_period_range_header`
- `cover_metadata.py`：公司识别支持 `公司=CODE (全称)`、`公司: CODE - 全称`；无完整日期时从 `本期/期间：YYYY-MM` 按月末推导；测试 `test_cover_metadata_a8t.py`（3）
- `run_detail_workbook_pipeline.py` 单边资产负债表布局检测（ERP 导出：表头行 B=年初余额/C=期末余额、A 列标签），不再按双边误解析出垃圾键；单边分支内 `预提费用` 并入 `其他流动负债`（真实 BS 预提 109,884.54、其他流动负债显式 0，alias 回退拿不到值导致 stage1 门禁差 -109,884.54）；测试 `test_balance_sheet_single_sided.py`（3）
- 锁定模板明细写入跳过非确认输入单元格（H 列第二账面值/审定额列不在 confirmed_input_cells，锁定模板下写 H6 抛 ProtectionViolation）；测试 `test_locked_detail_write.py`（2）
- `stage2_postfix_key_sheets` 职工薪酬/股权投资直写块跳过公式单元格（G6 `=F6` 被静态值覆盖触发 template_formula_changed）

**第二批（序时账解析——根因）**

- `load_journal_rows_from_xlsx_xml` 只探测金蝶式表头（科目编码/科目名称/方向/金额），Oracle ERP 序时账识别失败后静默回退到固定列字母 → tb_code 解析成"日记帐摘要"、客商两列全空，下游全部 journal_unmatched。新增 ERP 表头探测（`会计科目代码` + `往来描述`/`供应商名称`）按表头名取列
- ERP 每行有两个合法客商列（AP 子模块供应商名称、往来段描述），而管线不变式"vendor_name == counterparty_desc"诞生于两字段同源单列的时代，`build_journal_entity_index` 遇真实双列即抛 conflicting_journal_counterparties。改为按科目语义择一：内部往来科目取往来描述，其余取供应商名称，各自以另一列兜底并剔除禁用占位词（默认值）；既有冲突守卫测试语义不变
- 测试 `test_journal_erp_header.py`（6）：修复前 4 failed；真实 TBD 验证 2,239 条干净分录、1124050000+天猫 65 行、0 垃圾行

**第三批（写入侧与复核侧候选集统一）**

- 写入侧用全序时账无过滤选发生日期/业务内容，复核侧 `strict_journal_candidates` 只认表根科目（2241 等），1124 内部往来重分类行被两边反向处理 → journal_unmatched 与 source_mismatch 并存。严格候选规则下沉到 pipeline 共享，两侧同用，并扩展"本行 tb_code 精确匹配"接纳重分类来源科目；测试 `test_journal_candidate_unification.py`（4）

**第四批（验收一致性）**

- 新增共享 `resolve_tb_counterparty`：TB 辅助名有效一律保留（修复 1124050000 上淘宝/阿里上海/阿里网络被最大发生额序时账客商天猫整体改标），禁用/空名取该科目最大单笔发生额的序时账客商（保留 安永/平安/阿里商旅/管仁良 的正确解析），`ALLOWED_EXCEPTION_COUNTERPARTIES`（待查资金入账）按例外名单解析；group_rows 与复核 expected 键同用此规则（修复成对 source_mismatch）
- 复核业务描述规范化补传 account_name 上下文（填入侧有、复核侧无 → SETTLEMENT_INV_MATCH vs 进项税暂估 不一致）
- 2241990000 待查资金入账按 credit_end-debit_end 保留净额 -32,537.99（原取 credit_end=0 被丢弃 → 明细合计差 +32,537.99）
- `stage2_postfix_key_sheets` 新增其他流动负债（预提费用）BS 证据行直写（修复分类汇总链 -109,884.54 差异）
- 写入记录新增 `_written_cells`（只记实际写入单元格），复核不再向锁定模板跳过列索要数值（预收 H6）
- 复核"非六科目无显式证据映射"分支豁免 SEMANTIC_EXEMPT_SHEETS（银行存款/应交税费为聚合行，天然无单一来源单元格；银行无对账单时另有 no_bank_account_detail 边界声明）
- 复核对例外名单客商（待查资金入账）跳过序时账匹配要求，改记 needs_materials 提示（需银行流水另行佐证）
- 语义占位门禁的小额容限（≤1000 且有占位行）从仅其他应付款推广到全部必填明细表（预收账款 -0.32 适用）
- 测试 `test_a8t_validation_consistency.py`（9）：修复前 8 failed

**复测验收矩阵（`K08 REAL RUN OK`，日志 `k08-real-run/run.log`）**

- 11 个文件全部注册（含 2 个原始 .xls）；主体识别 A8T；自动选中 2026-07 最新 TB/TBD/BS；2023—2025 六份自动列为历史参考（不进 comparison）；无提问直接 resolved
- 只创建一次生成任务（run state: succeeded）
- 最终产出评估明细表主成果（531,535 字节，openpyxl 可打开），用户可见成果仅 1 个，显示名"阿里云飞天（北京）云计算有限公司评估明细表（2026-07-31）.xlsx"；内部校验 JSON 不列示
- 11 个原件 SHA256 前后一致；锁定模板哈希不变；delivery gate: pass；xls_conversion_report 记录 balance_sheet.xls 转换（XDO_METADATA 隐藏表跳过；PL.xls 为参考证据非生成输入，不经转换，摘要经 xlrd 读取）
- 声明的证据边界（不阻塞、如实列示）：银行存款无对账单逐户明细（no_bank_account_detail）、预收账款 -0.32 客商为禁用占位词（forbidden_term）
- 明细勾稽：其他应付款明细合计 14,043,611.33 = BS（含待查资金入账 -32,537.99 净额行）；分类汇总负债全链差异清零；资产负债表 11,934.09 = 11,934.09 平衡
- Excel/WPS 真实打开验证：本机无自动化手段，以 openpyxl/zip 结构校验 + fullCalcOnLoad 代替，未做真实 Office 打开确认（如实标注）

**全量回归**：`tests/technical_platform` + `tests/report_review_app` + `tests/report_review_server` 共 **1774 passed, 1 skipped**（9m40s，日志 pytest-full-k08.log，EXIT=0；较 K07 基线 1746 净增 28 个本轮新测试）
