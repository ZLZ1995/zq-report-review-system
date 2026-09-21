# 执行账本：普通对话、信息查询与任务理解协议兼容（K00—K10）

> 任务书：`docs/technical_platform/KIMI_WORK_FIX_CONSULTATION_ROUTING_AND_PROTOCOL_COMPATIBILITY.md`（主仓库版本，内容已完整阅读）。
> 逐阶段记录命令、测试、失败证据、修改文件和结论。

## K00 建立基线和执行账本

### 0. 已完成的指定阅读

- 主仓库 `AGENTS.md`（工作树已删除，从 HEAD 读取；核心：Word 原生最小编辑、中文禁用 PowerShell 内联、只读/生成路由硬约束）；
- `agent-diagnose-runtime/SKILL.md`、`agent-tdd-fix/SKILL.md`（均在主仓库 `.codex/skills/`，验收仓库无此两个 skill）；
- `KIMI_WORK_FIX_XLS_UPLOAD_AND_CLARIFICATION_RESUME.md`（515 行）、`KIMI_WORK_FIX_MULTIPERIOD_MATERIAL_ROUTING.md`（296 行）全文；
- 本任务书全部引用代码的初步核实（见下）。

### 1. 两个工作区的关系（§0.1 门禁）

- 主仓库 `D:/1/1/ai-excel-agent`：独立 clone，分支 `master`，HEAD `cbc7d94`（5 个提交的本地快照历史，含大量用户未提交改动：skill 文档/manifest、config 等；`AGENTS.md` 在工作树被删但 HEAD 有）。`src/asset_based_agent/technical_platform/` 下**无** intent_policy/input_gateway 等模块。
- 验收仓库 `D:/ZQ-Acceptance/local-feature-checkout`：独立 clone（非主仓库 worktree），分支 `codex/local-platform-feature-update`，HEAD `0ed4128`（P 轮提交，工作树干净）。同一 GitHub remote（ZLZ1995/zq-report-review-system）。另有 `D:/ZQ-Acceptance/release-checkout`（d1276a6，codex/platform-sync-20260917）。
- **结论：唯一权威修改工作区 = `D:/ZQ-Acceptance/local-feature-checkout`**（当前发布链源码）。主仓库是文档/Skill 编辑工作区，本轮不在主仓库改代码，避免双补丁分叉。
- 注意：本会话 GitHub 不可达（connection reset / 400），无法 fetch 比较远端引用；线上 SHA 无法在本解析（partial clone）。记录为外部状态，不影响本地施工；K10 本来就需要另行授权。

### 2. 当前运行 EXE 溯源（不以文件时间猜测）

- 正在运行进程 PID 20308：`D:\ZQ-Acceptance\acceptance-builds\20260920-0615\ZQ技术平台\ZQ技术平台.exe`。
- 构建记录：`run-build-20260920-0615.bat` → `cd D:\ZQ-Acceptance\local-feature-checkout && scripts\build_technical_platform.py`，构建于 2026-09-20 06:15，EXIT=0。
- 构建时点 HEAD 介于 e689570 之前（06:15 < 08:23 a742b11）：**包含** G01/G02 意图模块（TOC 扫描确认 intent_policy/input_gateway/turn_context/intent_schema/agent_profiles 各 1 命中），**不包含** a742b11（material evidence）与 2135fb4（错误分类）：`material_evidence`/`MaterialEvidence` 字符串 0 命中。
- 仓库内 `dist/technical_platform/ZQ技术平台.exe` 为更旧的 2026-09-18 构建（无 intent 模块），非当前测试对象。
- 版本清单：`ZQ-Workspace-0.2.10-*.json`（0.2.10，sequence 5，data_schema 11）。

### 3. 线上服务端只读快照（2026-09-20，本会话实时抓取）

工件：`k-round-consult/k00_online_capabilities.json`、`k00_online_openapi.json`（工作区）。

- `GET /api/v1/capabilities` → 200：`schema_version=1`、`protocol_version=1`、`build_sha=52eed3496e06f7b6d49a0028aa51e3b8797679fd`；capabilities 含 task_understanding=1 等 15 项，**无 material_evidence**。
- `GET /openapi.json` → 200：58 个 Schema；**无 MaterialEvidence**；`EvidenceRef` 仅 id/name/sha256 且 `additionalProperties=false`。
- 结论：任务书 §1.3 的协议漂移**复测成立**。线上 build SHA 在本地 clone 中无法解析（partial clone + GitHub 不可达），服务端部署提交待 K10 授权后对账。

### 4. 四者版本对照（§1.4 核实）

| 层 | 状态 |
|---|---|
| 本地源码（0ed4128） | 客户端 `EvidenceRef.evidence` + 空值剔除序列化（a742b11）；服务端 `compat_agent_contracts.MaterialEvidence` 已定义；`remote_auth_service.py:274` 有 `material_evidence` 能力检测；`intent_policy.py:138` 有 consult/answer 分支 —— 部分修复**仅在源码** |
| 运行中 EXE（0615） | 有意图模块，无 material_evidence/错误分类 → 介于新旧之间 |
| 仓库 dist EXE（0918） | 更旧，非当前测试对象 |
| 线上服务端（52eed34） | 无 MaterialEvidence、无 material_evidence 能力 |

即任务书 §1.4 的三种情形同时存在：源码修复未进 EXE、服务端未部署、接线完整性待 K01/K03 测试判定。

### 5. 既有相关测试资产（K01 候选落点）

- `tests/technical_platform/test_input_gateway.py`、`test_intent_policy.py`、`test_natural_language_intent.py`、`test_agent_controller.py`、`fixtures/intent_eval_zh.jsonl` 等（存在性已核实，K01 逐一运行定基线）。

K00 验收：唯一权威工作区已明确；源码/EXE/GitHub/线上四者版本已固定；不改动任何业务代码。✅

---

## K01：失败测试冻结（2026-09-20）

新增 `tests/technical_platform/test_consultation_routing.py`（初版 9 用例）。修复前基线：8 红 1 绿（K01-5 旧服务端降级守卫绿）。覆盖：社交问候不联网不建任务、能力咨询空 skill_ids、一般知识不规划、阶段 1 请求不夹带 MaterialEvidence/正文、旧服务端剥离扩展字段、422→RequestSchemaError、能力/OpenAPI 契约检查、咨询保留 pending 澄清、咨询不建任务不改附件不计费。

## K02：协议兼容矩阵（2026-09-20）

- `remote_auth_service.py`：422 → `RequestSchemaError`（error_code='http_422'，http_status=422）；`RequestSchemaError.__init__` 增加 error_code/http_status 参数，旧断言兼容。
- 新增 `src/asset_based_agent/report_review_server/contract_check.py`：`check_capabilities_against_openapi` 双向核对（声明能力缺 Schema / 有 Schema 未声明能力）。
- 测试：`tests/report_review_app/test_protocol_compat_matrix.py`（8）、`tests/report_review_server/test_contract_check.py`（3），全绿。

## K03：Intent Analyst 与本地裁决接通（2026-09-20）

- 新增 `src/asset_based_agent/technical_platform/turn_router.py`（TurnRouter）：① 精确匹配社交快速通道（§4.2 允许的性能优化，其余一律结构化模型判断）；② 阶段 1 轻量理解（仅附件身份 EvidenceRef、截断 240 字符的 Skill 描述、含待澄清上下文）；③ answer/cancel/refuse 不碰任务状态；④ plan/ask/browser 才进 `AgentController.prepare` 全量链。本地裁决 = `validate_understanding` 契约校验（范围外文件/未知 Skill 拒绝）+ TurnRouter 分支绑定。
- `routing.py` 新增 `ConsultWorker`（QThread，九类错误分类映射）；`task_events.py` CompletionEventRelay 增加 `consult` 生命周期；`app.py` submit() 改走 `register_consult_worker`/`consult_finished`：answer/cancel/refuse 直接显示；execution 用 outcome.pending 创建 UnderstandingWorker 走原链；失败时恢复 composer 文本，用户输入不丢失。
- `intent_eval_zh.jsonl` 126→140 条：新增咨询（含平台查询/能力询问）4、取消 2、否定 2、条件句 2、澄清恢复（新类别）4。
- 既有调用次数断言按 §4.2 两阶段设计更新：`test_compound_window.py`、`test_browser_window.py`（子进程内嵌脚本同步改为 understand×2）。

## K04：Conversation Agent 非执行通道（2026-09-20）

- ConversationReply 复用 `TurnOutcome`（§7 允许）；answer 只写消息，不建 run/plan/artifact、不预留计费（测试断言数据库只有消息记录）。
- ConsultWorker 断网/登录失效/余额不足/Schema/能力/提供商/内部错误分别提示，均不含 "Skill" 字样（新增 5 个 ConsultWorker 测试）。

## K05：平台查询与文件只读问答（2026-09-20）

- 新增 `src/asset_based_agent/technical_platform/platform_queries.py`：模型判 consult 后，平台查询（项目文件数/已安装 Skill/任务状态/版本/项目列表）用本地数据库与注册表的确定性数据回答，不让模型编造；文件只读问答只对本轮明确选择或提及的文件取可见摘要（可见工作表、限行限列、无绝对路径、无隐藏表、无二进制），第二次轻量调用请模型据摘要回答，并落 `event` 审计消息。
- `remote_auth_service.py` 新增 `server_build_info()`（只读 GET /capabilities）。
- 测试 `tests/technical_platform/test_platform_queries.py`（9）：数据库一致性、真实注册表、真实任务状态、版本、可见摘要落地+审计、指代词限定已选文件、历史附件不串入、未指向文件不触发落地。

## K06：咨询/澄清/执行状态隔离（2026-09-20）

- 产品规则（契约约束下的确定性裁决）：待澄清 + plan → **显式继续**原任务（prepare resume 恢复原 TurnEnvelope 约束），并追加告知消息给出"取消"出口；待澄清 + cancel → 取消原任务；待澄清 + consult → 回答且 pending 原样保留。契约 `clarify` 意图仅允许 `ask` 决策，resume-answer 在线上协议中落为 execute/plan，故不以 message_intent 区分恢复/新任务——继续必须显式，绝不静默拼接。
- 测试 `tests/technical_platform/test_turn_state_isolation.py`（4）：恢复原 task_id、显式继续+告知、明确取消、咨询保留 pending。

## K07：错误分类与可观测性（2026-09-20）

- 新增 `ModelProviderError`（error_code='model_provider_error'）+ 服务端 provider 失败码映射（all_providers_failed 等 6 码）；ConsultWorker/UnderstandingWorker 均设独立分支。
- 422 文案收紧为"客户端与服务端版本不兼容，请更新客户端或服务端"（删"可能"）。
- `diagnostics.log_worker_failure` 增加 client_version/server_build 字段；`turn_router._call_with_request_id` 给阶段 1/落地调用异常附加 request_id，ConsultWorker 日志带 request_id——同一故障可按 request_id 关联 UI 与日志。
- 新增 4 测试：provider 错误独立分类、422 文案、ConsultWorker provider 提示、request_id 日志关联。

## K08：完整自动化回归（2026-09-20）

验收矩阵 C01–F03 全覆盖（社交矩阵参数化 6 短语；平台查询 5；文件问答 3；状态隔离 4；错误分类 4；协议 2；既有 E01–E04 由 automatic_routing/compound/browser/clarification_resume 套件覆盖）。

- tests/report_review_server + tests/report_review_app：450 passed, 1 skipped。
- tests/technical_platform 分段：a+非浏览器b 100；browser a-d 116；browser e-n 41；browser o-z 239；c-e 237；f-m 237；n-z 414 —— 合计 1384 passed。
- Ruff：本轮改动文件 0 错误（16 处自动修复 + 手工清理）；遗留 2 处为 remote_auth_service.py:633 既存代码（ConnectivitySupervisor._terminate），非本轮改动，按"不处理无关历史债务"保留。
- Mypy（--ignore-missing-imports --follow-imports=skip）：turn_router/platform_queries/contract_check 0 issues。
- 未删除、跳过或放宽任何旧测试；仅按 §4.2 两阶段设计更新 2 处调用次数断言。
