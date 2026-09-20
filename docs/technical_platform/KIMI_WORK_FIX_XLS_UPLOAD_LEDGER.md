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
