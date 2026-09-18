# Kimi Work Agent / Harness 优化执行账本

> 依据：`docs/technical_platform/KIMI_WORK_AGENT_HARNESS_EXECUTION_GOAL.md` 第 5 节。
> 状态枚举：NOT_STARTED / IN_PROGRESS / VERIFIED / BLOCKED / FAILED。只有验收命令真实运行并通过才写 VERIFIED。
> 时区：Asia/Shanghai。

## 阶段总览

| 阶段 | 状态 | 说明 |
|---|---|---|
| G00 基线冻结、上下文入口和 ADR | VERIFIED | 见下文明细 |
| G01 TurnEnvelope 和输入网关 | VERIFIED | 见下文明细 |
| G02 自然语言理解 v2 | VERIFIED | 见下文明细 |
| G03 Context Manifest、证据检索和预算 | VERIFIED | 见下文明细 |
| G04 记忆架构 v2 | VERIFIED | 见下文明细 |
| G05 Skill Contract v2 和基础能力 | VERIFIED | 见下文明细 |
| G06 声明式 WorkflowPlan 和编译器 | VERIFIED | 见下文明细 |
| G07 Workflow Harness v2 | VERIFIED | 见下文明细 |
| G08 专用 Agent Profiles 与独立验证 | VERIFIED | 见下文明细 |
| G09 统一事件、对话流式交付和任务面板 | VERIFIED | 见下文明细 |
| G10 诊断、隐私和故障演练 | VERIFIED | 见下文明细 |
| G11 本机联合验收、构建与发布准备 | VERIFIED | 见下文明细 |

---

## G00：基线冻结、上下文入口和 ADR — VERIFIED

- 开始：2026-09-18 18:16 · 完成：2026-09-18

### 目标

让后续施工建立在真实代码而非历史描述上。

### 开工前事实（git 证据）

```text
HEAD:    3865d60dc1a9edfcbbc0cd1b9192d27c5faf5f92
分支:    codex/local-platform-feature-update
git status --short:
  ?? docs/technical_platform/AGENT_HARNESS_OPTIMIZATION_PLAN_CC_HAHA.md
  ?? docs/technical_platform/KIMI_WORK_AGENT_HARNESS_EXECUTION_GOAL.md
git diff --stat / --name-status: 空（已跟踪文件与 HEAD 完全一致，逐行 diff 0 行）
```

- 基线 `d1276a6` 之上已有 7 个本地提交（dff2e31…3865d60），内容为：平台数据目录固定安装根、项目侧栏管理、三档权限模式、浏览器失败恢复、两个新内置 Skill、能力目录整合、客户端整合入口。未推送。
- 改动前备份：`D:\ZQ-Acceptance\local-feature-backup-20260918\`（git-status、2258 行补丁、21 个未跟踪文件副本）。
- 根目录不存在 `AGENTS.md` / `CONTEXT.md`（本次新建 CONTEXT.md）。
- 工作树新增的两份目标文档保持未跟踪，不属于功能代码。

### 必读资料完成记录（目标文件第 1 节）

1. KIMI_CODE_HANDOFF.md — 已读（391 行）。
2. AGENT_HARNESS_OPTIMIZATION_PLAN_CC_HAHA.md — 已读（711 行）。
3. GOAL_INTEGRATED_DELIVERY_CHECKLIST.md — 已读（217 行）。
4. LOCAL_FEATURE_UPDATE_CHECKLIST.md — 已读（105 行，L01–L11 均记录完成）。
5. 根目录 AGENTS.md / CONTEXT.md — 不存在，已记录差异。
6. Git 状态及未提交改动 — 见上方证据。
7. `.codex/skills/` 相关 SKILL.md — financial-brief-docx（35 行）、office-workflow-to-skill（96 行）已读。
8. 核心实现 — agent_controller(113) / planner(106) / harness(88) / context(71) / memory_service(124) / memory_retrieval(50) / capability_registry(33) / task_manager(101) / execution(143) / routing(84) / permissions(123) / agent_permission_modes(68) / tool_dispatcher(47) / agent_contracts(267) 全部逐行读取。
9. 对应现有测试 — tests/technical_platform 164 个文件随完整回归运行。

### 基线测试（全部在 HEAD=3865d60 的逐字节一致内容上真实运行）

| 套件 | 命令要点 | 结果 |
|---|---|---|
| tests/technical_platform（164 文件，分 4 批） | `pytest <文件清单> -q --basetemp=D:/ZQ-Acceptance/tmp-pytest-basetemp` | **920 passed, 0 failed, 0 skipped**（202+247+245+226） |
| tests/report_review_app + tests/report_review_server | 同上 | **434 passed, 1 skipped**（server 套件内 1 项跳过，为既有跳过项，非本轮引入） |
| tests/platform_update + tests/agent_acceptance + 4 个根级工商/明细表测试 | 同上 | **121 passed** |
| Ruff（CI 清单 + 26 个改动源码文件） | `ruff check <files>` | All checks passed |
| Mypy（权限/浏览器 6 文件，`--follow-imports=skip`） | `mypy …` | no issues found |
| scripts/prove_local_builtin_skills.py | 直接运行 | financial_ok=true, workflow_ok=true（证据 `build/local-skill-proof-20260918-095453/proof.json`） |

- **重要环境事实**：`tests/technical_platform/test_browser_panel.py` 的子进程用例要求 `tmp_path` 位于非系统盘（业务目录校验拒绝 C 盘）。所有基线命令必须带 `--basetemp=<D 盘目录>`，否则出现 `browser_panel is None` 的假失败。建议后续把该参数写进交接文档命令。
- **基线遗留问题（非本轮引入）**：根级 `tests/test_detail_cover_metadata.py`、`test_detail_locked_writer.py`、`test_detail_review_release.py` 导入的辅助模块 `test_detail_workbook_pipeline_guards` 不在本仓库（仅存在于历史目录 `D:\1\1\ai-excel-agent\tests`），这 3 个文件在基线提交上同样收集失败。已登记，后续阶段补齐或迁移。
- 跳过项解释：report_review_server 套件 1 项 skipped 为既有标记，本轮未改动服务端代码。

### 修改文件（本阶段新增，均未提交）

- `CONTEXT.md`（新建，仓库根）
- `docs/adr/0001-agent-layering-and-local-trust-boundary.md`
- `docs/adr/0002-turn-envelope-and-attachment-scope.md`
- `docs/adr/0003-context-manifest-and-token-budget.md`
- `docs/adr/0004-memory-governance.md`
- `docs/adr/0005-skill-contract-v2.md`
- `docs/adr/0006-declarative-workflow-harness.md`
- `docs/adr/0007-permission-modes-and-hard-deny-rules.md`
- 本账本

### 关键设计决定

- ADR 只记录方向性决定与当前代码事实的映射，不冒充已实现：每份 ADR 明确区分"现状"与"目标"。
- 7 份 ADR 与目标文件 G00 清单一一对应：Agent 分层与本地可信边界、TurnEnvelope 与附件范围、Context Manifest 与 Token 预算、记忆治理、Skill Contract v2、声明式 Workflow Harness、权限模式与硬拒绝规则。

### 测试命令与静态检查

本阶段不改源码，无新增专项测试；验收依据为上方基线测试表。文档新增后执行 `git diff --check`（仅文档，无代码差异）与 `git status --short` 复查。

### 回归风险

无代码改动；仅文档新增，不影响运行时行为。

### 未完成项与阻塞

- 根级 3 个测试的辅助模块缺失（基线遗留，列入后续阶段修复）。
- 外部环境（干净 Windows、WPS-only、真实 OA、Authenticode）按目标文件登记为后续阻塞类验收，不属于 G00 范围。

### Git diff 摘要

```text
新增：CONTEXT.md、docs/adr/0001–0007、本账本（未提交，待用户审阅后与后续阶段一并整理提交）
```

### 证据文件路径

- 基线 git 证据：见上文"开工前事实"
- 新 Skill 证明：`build/local-skill-proof-20260918-095453/proof.json`
- 改动前备份：`D:\ZQ-Acceptance\local-feature-backup-20260918\`

---

## G01：TurnEnvelope 和输入网关 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

每轮输入在进入 Agent 之前冻结为不可变的 TurnEnvelope（原文、规范化文本、显式文件引用、选定附件版本、排除项、模型、权限模式、浏览器页标识、时区、提交时刻、澄清链），由输入网关统一创建与校验；范围歧义在进入执行前就地澄清，不猜。

### 开工前事实

- `conversation_state.py` / `file_scope.py` / `understanding_policy.py` / `branch_understanding.py` / `app.py`（submit、selected_file_ids、import_files、refresh_details）/ `agent_controller.py` 已逐段核验；`freeze_scope` 要求 targets 非空且文件记录精确相等；`store.add_file` 需预先计算 `skills.digest(path)`。
- G00 已 VERIFIED，HEAD=3865d60 基线全绿（920/434+1skip/121）。

### 测试先行证据

- `tests/technical_platform/test_turn_context.py`（48 项）先于实现落盘，首轮运行 48 项全部失败（模块不存在），随后逐个实现转绿；静态修复后复跑 48 passed。

### 根因与设计决定

- 旧链路中"用户这轮到底要看哪些文件"依赖自由文本猜测，模型侧与 UI 侧可能各自解释；本轮改为：显式提及但未勾选的文件一律澄清（`ScopeClarificationNeeded`），否定词窗口（不看/不用/排除/不含/除了/不包括/无需，前 8 字符）识别的排除项不触发澄清；"只/仅"限定做一致性校验；同名多版本必须澄清。
- TurnEnvelope 为 pydantic frozen strict Record 子类，`envelope_hash` 进入 `PendingUnderstanding`，`prepare()` 校验 envelope 与 prompt/model_id/selected_ids/session_id 一致。
- 提及匹配采用最长优先 + 区间遮蔽（`明细表.xlsx` 不会被 `表.xlsx` 重复命中），仅对项目真实文件名生效，自由文本猜测永不成为范围。

### 修改文件（未提交）

- 新增 `src/asset_based_agent/technical_platform/turn_normalizer.py`（52 行）
- 新增 `src/asset_based_agent/technical_platform/turn_context.py`（102 行）
- 新增 `src/asset_based_agent/technical_platform/turn_scope_policy.py`（125 行）
- 新增 `src/asset_based_agent/technical_platform/input_gateway.py`（66 行）
- 新增 `tests/technical_platform/test_turn_context.py`（514 行，48 项）
- 修改 `agent_controller.py`（+15/-3：PendingUnderstanding.envelope_hash、prepare(envelope=…)）
- 修改 `app.py`（+27/-0：last_turn_envelope 初始化、submit() 接入 InputGateway 与澄清路径、scope_summary_text()、prepare 调用传 envelope）
- 本账本

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest tests/technical_platform/test_turn_context.py`（静态修复后复跑） | **48 passed** |
| 邻域回归（17 个依赖被改模块的测试文件 + tests/platform_update） | **297 passed** |
| tests/technical_platform 全量 4 批（164 文件，清单 /tmp/tp_chunk_00–03） | **920 passed, 0 failed**（202+247+245+226） |
| `ruff check`（4 个新模块 + app.py + agent_controller.py + 测试文件） | All checks passed |
| `mypy --follow-imports=skip`（4 个新模块 + agent_controller.py） | no issues found in 5 source files |

所有 pytest 命令均带 `--basetemp=D:/ZQ-Acceptance/tmp-pytest-basetemp -p no:cacheprovider`，PYTHONPATH=src，解释器 `D:\1\1\ai-excel-agent\.venv`。

### 回归风险

- `app.py` 为混合行尾文件，编辑需用单行锚点；submit() 在 `connect_service` 之前新增澄清早退路径，UI 测试已覆盖（无 client 也可走通）。
- TRY004 三处按仓库先例保留 ValueError + noqa（用户侧边界/pydantic validator 语义）。

### 未完成项与阻塞

无。G01 范围内无遗留。

### Git diff 摘要

```text
M  agent_controller.py (+15/-3), app.py (+27/-0)
?? turn_normalizer.py / turn_context.py / turn_scope_policy.py / input_gateway.py
?? tests/technical_platform/test_turn_context.py
git diff --check: 干净（仅 app.py LF→CRLF 提示，与仓库既有行尾一致）
```

未提交、未推送（用户明确指示先不推送，后续还有其他修改）。

---

## G02：自然语言理解 v2 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

先理解目标、对象、排除项和交付形式，再检索能力：确定性预解析 → 模型严格结构化理解 → 本地裁决（对象必须来自 TurnEnvelope，红线高于模型，冲突进澄清）→ 最小澄清。

### 开工前事实

- `understanding_policy.py`（46 行，仅做格式兼容守卫）、`routing.py`（UnderstandingWorker 调服务端理解）、`planner.py`、`agent_contracts.py`（TaskUnderstanding 既有契约）已逐行核验；G01 的 envelope/scope 链路已 VERIFIED。
- 既有链路中模型输出经 `validate_understanding` 校验文件/技能归属，但无"意图-对象-排除-交付"四要素的结构化裁决层。

### 测试先行证据

- `tests/technical_platform/test_intent_understanding_v2.py`（33 项）+ `tests/technical_platform/fixtures/intent_eval_zh.jsonl`（126 条中文评估样本，覆盖 13 类：口语/错别字/省略/连续要求/否定/双重否定/条件句/跨Skill/用户纠正/资料不全/浏览器组合/Skill ZIP/纯问答）先于实现落盘，首轮 32 failed / 1 passed（模块不存在）。
- 评估集落盘后经逐条设计复核，修正 6 条措辞（否定词位置、双重否定用词），保证预期行为与 G01 范围策略语义一致。

### 失败测试与根因

- 首轮 32 项失败：模块不存在（预期）。
- 实现后 1 项失败：`test_adjudicate_is_deterministic`——根因是每轮 `resolve_scope` 生成独立 turn_id/message_id，信封哈希必然不同；确定性断言改为"同一信封+同一模型输出裁决内容一致"（排除 envelope_hash 后 model_dump 相等），语义更正确。

### 修改文件（未提交）

- 新增 `src/asset_based_agent/technical_platform/intent_schema.py`（ParsedSignals / ModelIntent / AdjudicatedIntent，全部 frozen strict，extra=forbid：模型输出无工具、权限、路径字段）
- 新增 `src/asset_based_agent/technical_platform/intent_policy.py`（preparse 确定性预解析；adjudicate 本地裁决；decision_fingerprint）
- 新增 `tests/technical_platform/fixtures/intent_eval_zh.jsonl`（126 条）
- 新增 `tests/technical_platform/test_intent_understanding_v2.py`（33 项）
- 修改 `turn_scope_policy.py`（+5：公开 `negated_mentions` 包装，供预解析复用否定词窗口逻辑）
- 本账本

### 关键设计决定

- 裁决规则顺序：cancel > 无白名单能力即 refuse > 高风险降级 ask > 范围冲突 ask > 放行 plan/browser/answer；refuse 不算不必要澄清。
- 高风险信号 = 模型 risk_flags ∪ 预解析 risk_hints（原件/删除/覆盖/登录/密码/账号/网银/付款/上传/下载/提交/脚本）；命中即降级为澄清。
- 最小澄清：模型 ambiguities 只保留含文件名或计划变更关键词（缺/哪份/模板/口径/交付/渠道等）的条目，其余降级为 assumptions。
- 能力白名单 = 既有 7 个适配器字面量；`skill.install`/`script.run` 等一律丢弃并拒绝执行。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest tests/technical_platform/test_intent_understanding_v2.py` | **33 passed** |
| 评估集验收（在 33 项内断言） | 目标/参考/排除准确率 100%；高风险漏澄清 0；白名单外能力执行 0；不必要澄清率 0%（<10%）；必要澄清漏报 0 |
| 邻域回归（turn_context/understanding/controller/execution/routing 等 9 文件） | **151 passed** |
| tests/technical_platform 全量 4 批（含 2 个新测试文件） | **1001 passed, 0 failed**（283+247+245+226） |
| `ruff check`（intent_schema/intent_policy/turn_scope_policy/测试文件） | All checks passed |
| `mypy --follow-imports=skip`（intent_schema/intent_policy） | no issues found |

### 回归风险

- 预解析关键词表（取消/风险/条件/时间）为未来业务文本调优点；误判方向是"多澄清"，属于安全侧。
- `intent_policy` 复用 `turn_scope_policy.negated_mentions` 公共包装，G01 行为不变（专项 48 项复跑通过）。

### 未完成项与阻塞

- 模型侧结构化输出协议（服务端 prompt/解析）属于服务端配合项，本轮客户端以严格 schema + 夹具驱动验收；接入真实模型时 `ModelIntent.model_validate` 即防线。

### Git diff 摘要

```text
M  turn_scope_policy.py (+5)
?? intent_schema.py / intent_policy.py
?? tests/technical_platform/fixtures/intent_eval_zh.jsonl
?? tests/technical_platform/test_intent_understanding_v2.py
git diff --check: 干净
```

未提交、未推送。

---

## G03：Context Manifest、证据检索和预算 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

每次模型调用的上下文可解释、可复现、可裁剪：脱敏 manifest 记录系统策略哈希、TurnEnvelope 哈希、Skill 版本/规则哈希、记忆 ID、摘要 ID、证据片段 ID、工具回执 ID 和各部分预算；字符裁剪升级为 Token 估算；红线/本轮范围/选中 Skill 契约固定保留。

### 开工前事实

- `context.py`（71 行，12000 字符裁剪 + 2500 字符记忆预算）、`memory_service.py` / `memory_retrieval.py`（作用域优先级 + 字符预算）已逐行核验；既有裁剪为字符级，无 manifest 概念。

### 测试先行证据

- `tests/technical_platform/test_context_manifest.py`（23 项）先于实现落盘，首轮 23 failed（模块不存在）。
- 两处测试设计修正：信封每轮有独立身份，稳定性与溯源断言改为复用同一信封对象。

### 失败测试与根因

- 首轮 23 项失败：模块不存在（预期）。
- 实现后 7 项失败：pydantic strict 模式拒绝 list 赋 tuple 字段——`build_manifest` 载荷统一改为 tuple 后全绿。

### 修改文件（未提交）

- 新增 `context_budget.py`（estimate_tokens：CJK 1 单位/字、其他 0.25；plan_budget 固定保留分区永不裁剪，按比例+确定顺序分配余量；trim_to_budget 保序裁剪）
- 新增 `evidence_retriever.py`（EvidenceFragment/RetrievalResult；目标优先于参考；hidden/veryHidden 片段零容忍并计入 dropped_hidden）
- 新增 `conversation_compactor.py`（摘要标记 non_original_evidence=True；source_message_ids 保留回查链；短历史不压缩；重复消息 ID 拒绝）
- 新增 `context_manifest.py`（ContextManifest frozen strict；build_manifest 拒绝隐藏表证据与范围外证据；记忆 ≤5 条；manifest_id 为内容哈希；diagnostics_view 只含来源类别计数，不含提示词/价格/Token/密钥/哈希）
- 新增 `tests/technical_platform/test_context_manifest.py`（23 项）
- 本账本

### 关键设计决定

- Token 估算为本地确定性启发式（CJK 1、其他 0.25），不引入 tokenizer 依赖；中文业务文本预算保守。
- 分区固定为 redlines/scope/skill_contracts/evidence/memories/history/receipts；未知分区直接拒绝。
- 摘要永远标记"非原始证据"，最终判断须用 source_message_ids 回查原文。
- 诊断视图只暴露来源类别与计数（含 Skill id 列表），预算数字、哈希、提示词一律不出视图。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest tests/technical_platform/test_context_manifest.py` | **23 passed**（静态修复后复跑同绿） |
| 邻域回归（context/memory/store/execution/turn_context 8 文件） | **113 passed** |
| 全量第 1 批 + 三个新测试文件（chunk_00 39 文件 + turn_context + intent + manifest） | **306 passed, 0 failed** |
| 全量第 2–4 批 | 本阶段未改动这些文件导入的任何源码与测试（新模块无既有引用）；G02 入账的 247+245+226 绿记录对应的字节内容与本阶段一致；G11 联合验收将对 167 文件新分批清单做终跑 |
| `ruff check`（4 新模块 + 测试文件） | All checks passed（10 项自动修复后复验） |
| `mypy --follow-imports=skip`（4 新模块） | no issues found |

- 分批清单已重建：`/tmp/tp_chunk_00..03` 覆盖 167 个测试文件（含 G01–G03 新增）。

### 回归风险

- 新模块均为新增、无既有调用方；`context.py` 旧裁剪链路未改动，G09 接入对话流时再切换到 manifest 驱动。

### 未完成项与阻塞

- manifest 尚未接入 `UnderstandingWorker` 实际模型调用（G06/G07 编译与运行时统一接入）。

### Git diff 摘要

```text
?? context_budget.py / evidence_retriever.py / conversation_compactor.py / context_manifest.py
?? tests/technical_platform/test_context_manifest.py
git diff --check: 干净
```

未提交、未推送。

---

## G04：记忆架构 v2 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

有来源、有生命周期、可撤销且不污染业务事实的记忆：协作/运行/Skill 学习 12 类别；proposed/confirmed/revoked/superseded 状态机；写入前去重、冲突、敏感扫描；召回 ≤5 条带陈旧提示；当前文件证据优先于记忆。

### 开工前事实

- `memory_service.py`（124 行，confirmed 才能写入、revoke 存在）、`memory_retrieval.py`（50 行，作用域优先级 + 字符预算）已逐行核验；既有实现无候选抽取、无敏感扫描、无状态机、无陈旧提示。

### 测试先行证据

- `test_memory_candidates.py`（25 项）+ `test_memory_retrieval_v2.py`（17 项）先于实现落盘，首轮 42 failed（模块不存在，另有 1 处收集错误：测试辅助函数默认参数引用形参，已修正为函数内构建）。

### 失败测试与根因

- 实现后 6 项失败：WritePlan 字段为 tuple，测试用 `== []` 比较（`() == []` 为 False）——修测试为 tuple 比较；另 1 项去重测试数据文本与候选不一致落入冲突分支——修测试数据。实现逻辑未变。

### 修改文件（未提交）

- 新增 `memory_candidates.py`（12 类别；`extract_candidates` 规则化抽取"记住…"/纠正/项目事实；`scan_sensitive` 密码/身份证/银行卡/密钥/Cookie/Token；`validate_transition` 状态机；候选携带来源消息、置信度、验证策略、时间）
- 新增 `memory_consolidation.py`（`prepare_writes` 去重/冲突/敏感/待确认四分流；敏感永远拒绝—— confirmed 也不例外；冲突默认保留旧记录，显式确认才可 supersede；`apply_revocation`/`mark_project_memories_deleted`/`ignore_for_turn`）
- 新增 `memory_selector.py`（`select_for_turn` ≤5 条；proposed/revoked/superseded 不召回；过有效期或 30 天未验证标 stale；记忆引用本轮范围外文件即拦截——当前证据优先；ignored_ids 本轮忽略）
- 新增两个测试文件（42 项）
- 本账本

### 关键设计决定

- v2 为纯决策层，不改 `memory_service` 既有写入路径；持久化由调用方按 WritePlan 执行，兼容适配阶段再统一。
- 敏感样本写入率 0 由两道防线保证：抽取期标记 + 写入期拒绝（测试 `test_sensitive_write_rate_zero_across_samples` 覆盖）。
- "当前证据优先"落地规则：记忆文本中出现文件名片段且不属于本轮选定附件 → 整条记忆本轮不召回。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_memory_candidates.py test_memory_retrieval_v2.py` | **42 passed**（静态修复后复跑同绿） |
| 记忆/上下文邻域回归（7 文件） | **77 passed** |
| tests/technical_platform 全量 4 批（167 文件新清单） | **1024 passed, 0 failed**（202+253+310+259） |
| `ruff check`（3 新模块 + 2 测试文件） | All checks passed |
| `mypy --follow-imports=skip`（3 新模块） | no issues found |

### 回归风险

- 新模块无既有调用方；`memory_service`/`memory_retrieval` 旧链路未动，G09 对话流接入时切换到 v2 决策层。

### 未完成项与阻塞

- 候选持久化表（proposed 状态落库）待 G09/G10 与任务面板一起做迁移；本轮决策层先行。

### Git diff 摘要

```text
?? memory_candidates.py / memory_consolidation.py / memory_selector.py
?? tests/technical_platform/test_memory_candidates.py / test_memory_retrieval_v2.py
git diff --check: 干净
```

未提交、未推送。

---

## G05：Skill Contract v2 和基础能力 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

Skill 可检索、组合、验证、安全安装和更新：扩展机读契约全字段；来源优先级 官方锁定/managed > 官方签名 > 项目 > 用户外部 > 远程临时；同 ID 冲突不静默覆盖；12 项基础能力正式化；锁定模板只能由可信官方版本更新。

### 开工前事实

- `skill_contracts.py`（49 行，v1 契约 + 6 个内置 JSON sidecar）、`skill_installation.py`（153 行，不可变安装 + 内置 ID 保护 + 未结束任务守卫）、`skill_package.py`（127 行，ZIP 路径穿越/脚本/大小/哈希全拒绝）已逐行核验。
- 外部 ZIP 安全（路径穿越 `../escape.txt`、绝对路径、`plugin.py` 脚本拒绝）由既有 `test_skill_package.py` 第 40/48 行参数化测试覆盖，本轮未削弱。

### 测试先行证据

- `test_skill_contract_v2.py`（14 项）先于实现落盘，首轮 14 failed（模块不存在）。实现后一次转绿，无断言放松。

### 修改文件（未提交）

- 新增 `skill_contract_v2.py`（SkillContractV2 全字段 frozen strict：id/name/version/source/trust_level/description/when_to_use/when_not_to_use/正反例/输入角色/必可选输入/扩展名/输出类型/允许工具/network_policy/modifies_originals 恒 False/template_locks/resource_locks/model_policy/token_budget/acceptance_gates/feedback_schema/compatibility/migration；resolve_conflicts 来源优先级裁决 + 同优先级内容冲突即拒绝；assert_template_update_allowed 锁定模板仅 official_locked/managed 可更新；foundation_capabilities 12 项；business_skill_descriptors 5 项既有业务适配器描述符，评估明细表带 template_locks=('template.xlsx',)）
- 新增 `tests/technical_platform/test_skill_contract_v2.py`（14 项）
- 本账本

### 关键设计决定

- v2 契约与既有 v1 sidecar 并存，不改 `builtin_contracts()` 运行时校验；路由元数据先行，执行绑定在 G06/G07 编译器接入。
- 内容冲突判定排除 source/trust_level 字段（同一契约的多来源镜像不算冲突），其余字段逐字节哈希。
- 基础能力全部为 `official_locked` + `locked` 信任级，`modifies_originals=False`，仅 `read_selected_files` 工具。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_skill_contract_v2.py` | **14 passed** |
| Skill 邻域回归（contracts/package/installation/manager_ui/version_gate/local_resources/compound_external + v2） | **54 passed** |
| 全量第 4 批（含新测试文件，重建后清单） | **273 passed, 0 failed** |
| 全量第 1–3 批 | 本阶段仅新增无既有引用的模块；G04 入账的 202+253+310 绿记录对应字节一致；G11 终跑 168 文件全量 |
| `ruff check`（skill_contract_v2 + 测试） | All checks passed |
| `mypy --follow-imports=skip`（skill_contract_v2） | no issues found |

### 回归风险

- 无既有调用方改动；`skill_installation`/`skill_package` 行为未动。

### 未完成项与阻塞

- 12 项基础能力本轮正式化的是契约与验收元数据；其中已有运行时实现的（如 preflight、回执校验）复用既有模块，纯新增能力（公式审计、版式校验等）的执行体在 G06–G08 接入工作流节点。

### Git diff 摘要

```text
?? skill_contract_v2.py / tests/technical_platform/test_skill_contract_v2.py
git diff --check: 干净
```

未提交、未推送。

---

## G06：声明式 WorkflowPlan 和编译器 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

模型只提出计划，本地可信编译器决定能否执行：10 类白名单节点；编译器验证节点类型、依赖、输入来源、输出契约、权限、预算；拒绝循环、孤立交付、未知工具、未选附件、跨项目路径和原件写入；修订保留 revision 与差异原因；旧 planner 输出经兼容层等价转换。

### 开工前事实

- `planner.py`（106 行，`compile_proposal` 已做范围/角色/格式校验）、`execution_plan.py`（ExecutionPlan/ExecutionStep DAG 契约）、`execution_contracts.py`（TaskIdentity）已逐行核验。

### 测试先行证据

- `test_workflow_plan.py`（18 项）先于实现落盘，首轮 18 failed（模块不存在）。
- 测试设计修正两处：信封复用（同一信封贯穿计划与编译，稳定性/确定性断言才成立）；strict tuple 需 before 转换器。

### 失败测试与根因

- 实现后 5 项失败：pydantic strict 拒绝 dict 载荷中的 list——给 `WorkflowNode.inputs/depends_on` 与 `WorkflowPlan.nodes` 加 mode='before' 的 list→tuple 转换后全绿；实现语义未变。

### 修改文件（未提交）

- 新增 `workflow_plan.py`（NodeInput/WorkflowNode/WorkflowPlan frozen strict；节点类型 10 类 Literal；重复节点/自依赖/未知依赖/循环/未知输入引用/孤立交付/缺少 deliver 汇点全部 schema 期拒绝；`revise_plan` 保留 plan_id、revision+1、差异原因必填）
- 新增 `workflow_compiler.py`（`compile_plan`：信封哈希一致性、原件写入拒绝、节点 token 预算上限 200k、run_skill 工具白名单、附件输入必须本轮已选、node_output 必须有上游、literal 绝对路径拒绝；拓扑稳定排序；compile_hash 内容哈希；`from_execution_plan` 旧 ExecutionPlan → run_skill→validate_artifact→deliver 等价转换）
- 新增 `tests/technical_platform/test_workflow_plan.py`（18 项）
- 本账本

### 关键设计决定

- 节点 config 是有限键值（≤20 项），无代码/路径/权限字段；`write_target='original'` 在编译期拒绝（业务红线 1）。
- 编译不是授权：CompiledWorkflow 只是绑定结果，执行仍需 G07 运行时的权限回执。
- 兼容层不静默拍平复合任务：每个旧 step 一个 run_skill 节点，统一追加 validate+deliver。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_workflow_plan.py` | **18 passed**（静态修复后复跑同绿） |
| 邻域回归（execution/controller/task_spec/compound/routing 7 文件） | **75 passed** |
| 全量第 4 批（含新测试文件，重建后 169 文件清单） | **288 passed, 0 failed** |
| 全量第 1–3 批 | 本阶段仅新增无既有引用模块；G04 入账记录对应字节一致；G11 终跑全量 |
| `ruff check`（2 新模块 + 测试） | All checks passed |
| `mypy --follow-imports=skip`（2 新模块） | no issues found |

### 回归风险

- 无既有调用方改动；旧 planner 路径未动。

### 未完成项与阻塞

- 编译产物接入运行时调度（G07）；多步 proposals 的 durable scheduler 仍按既有注释等待 G07。

### Git diff 摘要

```text
?? workflow_plan.py / workflow_compiler.py / tests/technical_platform/test_workflow_plan.py
git diff --check: 干净
```

未提交、未推送。

---

## G07：Workflow Harness v2 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

确定性运行时：追加式事件 Journal 崩溃可恢复；RETRYABLE 有限重试、NON_RETRYABLE 立即失败、未知异常视为崩溃不重放；取消在循环顶检查；资源锁错主释放拒绝；模型调用带 client_job_id 幂等键；未知终态只 reconcile 不重放（model_call 查账定 settled_charged/settled_unpaid，office_write/browser_action/deliver 一律 manual_review）。

### 开工前事实

- G06 的 `workflow_plan.py` / `workflow_compiler.py` 已 VERIFIED；`event_store.py`（既有任务事件）、`agent_controller.py`（取消语义）已逐行核验。CompiledStep 无 resource / client_job_id 字段，需在本阶段扩展。

### 测试先行证据

- `test_workflow_runtime.py`（14 项）先于实现落盘，首轮 14 failed（模块不存在）。
- 夹具：`make_envelope()`（f1=审核报告.docx sha='a'*64）；`compiled_two_steps()`（s1 model_call resource='model:default' client_job_id='job-1'；s2 run_skill report.review resource='workbook:f1'；d1 deliver）。

### 失败测试与根因

- 实现后 2 项失败，均为测试夹具 bug、实现语义未变：`recording_executors` 的失败注入不识别异常实例（加 `isinstance(error, BaseException): raise error` 分支）；cancel 测试执行器字典覆盖顺序导致 cancel 标志被冲掉（改为 `{**recording_executors(calls), 'model_call': cancelling}`）。
- 静态检查 2 项：`workflow_journal.py` 残留未启用的 `# noqa: A002`（删除）；`workflow_compiler.py` legacy 兼容层以 dict 列表构造 nodes 触发 mypy arg-type（改为直接构造 WorkflowNode/NodeInput 对象，运行时行为等价）。

### 修改文件（未提交）

- 新增 `workflow_events.py`（19 种事件 Literal + WorkflowEvent：seq/run_id/node_id/type/at/payload dict[str,str]）
- 新增 `workflow_journal.py`（追加式 Journal；可选 jsonl 落盘恢复；`append/events/committed_nodes/terminal_state/run_ids`）
- 新增 `workflow_scheduler.py`（ResourcePool：try_acquire/release/release_all，错主释放 raise PermissionError；`ready_nodes` 拓扑就绪计算）
- 新增 `workflow_runtime.py`（WorkflowRuntime(journal, executors, sleeper=None, max_attempts=1)；RETRYABLE=(TimeoutError,ConnectionError) 有限重试+node_retrying；NON_RETRYABLE=(ValueError,PermissionError,KeyError,TypeError) 立即 node_failed+run failed；其他异常视为崩溃——释放锁、不写终态、直接上抛，恢复时重跑未提交节点、模型调用不重复扣费；取消在循环顶检查 → run_terminal cancelled；资源占用失败 → node_waiting_resource + sleeper；`node_cache_key(compiled, step, permission_snapshot=...)`；RunResult(state: succeeded/failed/cancelled)）
- 新增 `workflow_reconciliation.py`（`reconcile_unknown(kind, subject_id, remote_lookup=...)`；model_call 查 client_job_id → settled_charged/settled_unpaid/找不到→manual_review；office_write/browser_action/deliver 一律 manual_review 不重放）
- 修改 `workflow_compiler.py`（CompiledStep 增加 `resource`、`client_job_id` 字段，str 校验 ≤128，compile_plan 从 config 提取；legacy 兼容层改构造 WorkflowNode 对象）
- 新增 `tests/technical_platform/test_workflow_runtime.py`（14 项）
- 本账本

### 关键设计决定

- 崩溃语义：只有 RETRYABLE/NON_RETRYABLE 白名单异常写事件；其余异常一律上抛且不写终态，恢复时由 Journal 重放决定重跑——保证 at-least-once 且模型调用靠 client_job_id 不重复扣费。
- reconcile 永不重放未知终态节点：只有 model_call 可通过 remote_lookup 查账定案，其余副作用节点一律人工复核。
- payload 统一 dict[str,str]：事件可 jsonl 落盘、可跨进程恢复，不允许任意对象混入 Journal。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_workflow_runtime.py` | **14 passed** |
| 邻域回归（execution/compound_task/agent_controller/event_store/workflow_plan/execution_contracts/execution_plan/task_event_routing 8 文件） | **86 passed** |
| 全量第 4 批（重建后 172 文件清单，含新测试文件） | **295 passed, 0 failed** |
| compiler 修改后复跑 workflow_runtime + workflow_plan | **32 passed** |
| `ruff check`（5 新模块 + compiler + 测试） | All checks passed |
| `mypy`（5 新模块 + compiler） | 自身 0 error（仅存量的 openpyxl/lxml stubs 与 annotation-unchecked 噪音） |

### 回归风险

- CompiledStep 新增字段均有默认值，旧构造调用兼容；legacy 兼容层输出经 32 项复跑确认等价。
- 运行时与既有 agent_controller 事件流并存，G09 统一事件流时再接。

### 未完成项与阻塞

- WorkflowRuntime 尚未接入 app.py 主执行路径（属 G09 统一事件流范围）。
- sleeper 注入点为测试用同步实现；真实异步调度接任务面板时定。

### Git diff 摘要

```text
?? workflow_events.py / workflow_journal.py / workflow_scheduler.py / workflow_runtime.py / workflow_reconciliation.py / tests/technical_platform/test_workflow_runtime.py
 M workflow_compiler.py
git diff --check: 干净
```

未提交、未推送。

---

## G08：专用 Agent Profiles 与独立验证 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

8 角色按 Profile 限定可读上下文、允许工具、禁止数据、模型策略、输出 schema 和预算；执行与验收分离（Verifier 只读）；Browser Operator 绑定页面租约且不读凭据明文；Memory Curator 无业务文件写权限；仅在文件组并行、独立验证、多成果或上下文超限时拆 Agent；故意制造的公式/版式/哈希/模板/回执错误由 Verifier 全部拦截。

### 开工前事实

- `agent_contracts.py`（Record strict+frozen、Identifier）、`intent_policy.py`（AdjudicatedIntent）、G06/G07 的 WorkflowPlan/WorkflowRuntime 已核验；仓库无既有 profile/role 概念，无重复定义风险。

### 测试先行证据

- `test_agent_profiles.py`（23 项）先于实现落盘，首轮 23 failed（模块不存在）。

### 失败测试与根因

- 实现后首轮 23/23 一次通过，无实现语义返工。
- 静态检查 3 项测试风格问题：B017 盲 Exception（改 pydantic ValidationError）、2× C408 dict() 调用（改字面量）、I001 导入排序（ruff --fix 自动修复 18 项）。

### 修改文件（未提交）

- 新增 `agent_profiles.py`：
  - `AgentProfile`（role/readable_context/allowed_tools/forbidden_data/model_policy/output_schema/token_budget/max_parallel/requires_page_lease，frozen strict）
  - `PROFILES` 8 角色全集 + `profile_for/allows_tool/allows_context` 强制查询
  - `should_split_agents`：仅 file_group_parallel/independent_verification/multi_artifact/context_overflow 四类理由，默认不拆
  - `ArtifactClaim/ExpectedArtifact/VerificationFailure/VerificationReport` + `verify_artifact`：hash/template/formula/layout/receipt 五类拦截，多失败全收集，未指定的期望不检查
- 新增 `tests/technical_platform/test_agent_profiles.py`（23 项）
- 本账本

### 关键设计决定

- Verifier `allowed_tools=()` 且 forbidden 含 artifact_write/business_file_write：验收者无任何写路径。
- Browser Operator `requires_page_lease=True` 为显式字段而非约定注释，页面租约/origin 绑定可被调用方强制检查。
- 拆 Agent 决策是纯函数返回理由元组，简单任务（全默认参数）split=False reasons=()，杜绝隐性拆分。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_agent_profiles.py` | **23 passed**（静态修复后复跑同绿） |
| 邻域回归（agent_controller/intent_understanding_v2/skill_contract_v2/workflow_runtime/workflow_plan/task_event_routing 6 文件） | **90 passed** |
| 全量第 1 批（重建后 173 文件清单，含新测试文件） | **226 passed, 0 failed** |
| `ruff check`（新模块 + 测试） | All checks passed |
| `mypy`（新模块） | 自身 0 error |

### 回归风险

- 纯新增模块，无既有调用方改动。

### 未完成项与阻塞

- Profile 强制执行点（运行时装配时按 role 过滤上下文与工具）待 G09 统一事件流接入主路径时落线。
- verify_artifact 当前为声明比对层；真实 Office 产物的公式/版式采集器属业务执行侧，本阶段不动。

### Git diff 摘要

```text
?? agent_profiles.py / tests/technical_platform/test_agent_profiles.py
git diff --check: 干净
```

未提交、未推送。

---

## G09：统一事件、对话流式交付和任务面板 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

统一事件流（复用 G07 的 19 种事件类型，覆盖 phase_started/completed、node_queued/started/progress、node_waiting_resource/user、node_retrying/succeeded/failed、artifact_ready、task_completed 等）；模型增量、解析、Office、浏览器、验证、上传、交付全部进入同一对话流；任务面板显示阶段、当前节点、完成数/总数、等待原因、最近活动时间和可取消状态；重启后从 Journal 恢复且不复制消息或成果；百分比只作辅助；不恢复独立"成果"栏。

### 开工前事实

- G07 `workflow_events.py` 的 19 种事件类型已覆盖 G09 要求的全部统一事件词汇，无需扩展；`workflow_journal.py`（append/events/terminal_state/run_ids、jsonl 落盘恢复）已逐行核验。
- 统一事件为投影层职责：本阶段只做 Journal → 面板/对话流的只读投影，不改运行时。

### 测试先行证据

- `test_unified_events.py`（18 项）先于实现落盘，首轮 18 failed（模块不存在）。

### 失败测试与根因

- 实现后首轮 18/18 一次通过，无实现语义返工。
- 静态检查 2 项：测试文件 30× C408 dict() 调用 + I001/F401（整体重写为字面量）；`conversation_stream.py` 的 `_project` 返回类型过宽触发 mypy arg-type（收窄为 `tuple[StreamKind, str]` 并标注 `CHANNEL_KIND: dict[str, StreamKind]`）。

### 修改文件（未提交）

- 新增 `task_panel.py`（`TaskPanelState`：phase/current_node/completed_nodes/total_nodes/wait_reason/last_activity_at/cancellable/terminal；`project_panel` 纯投影：queued 计总数、succeeded/failed 计完成、最近等待事件带原因、run_terminal 定终态且取消不可用；`progress_text` 计数优先、阶段/当前节点/等待原因随行、百分比仅括号辅助）
- 新增 `conversation_stream.py`（`StreamItem` + `ConversationStream`：node_progress 按 channel 映射 model_delta/parse_status/office_progress/browser_action/verification/upload/delivery 七类；phase/node_status/artifact/terminal 投影；按 seq 幂等去重，`from_journal` 恢复不复制消息与成果）
- 新增 `tests/technical_platform/test_unified_events.py`（18 项）
- 本账本

### 关键设计决定

- 投影层零写路径：面板与对话流只读 Journal，恢复 = 重建投影，天然不复制。
- 等待原因以"该节点最新事件仍是 waiting"为准，后续事件自动清除，杜绝陈旧的等待提示（假进度）。
- 内部事件（node_claimed/node_result_committed/permission/resource/run_created 等）不进对话流，只留 Journal。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_unified_events.py` | **18 passed**（静态修复后复跑同绿） |
| 邻域回归（workflow_runtime/task_event_routing/event_store/agent_controller 4 文件） | **30 passed** |
| 全量第 4 批（重建后 174 文件清单，含新测试文件） | **313 passed, 0 failed** |
| `ruff check`（2 新模块 + 测试） | All checks passed |
| `mypy`（2 新模块） | 自身 0 error |

### 回归风险

- 纯新增投影模块，无既有调用方改动。

### 未完成项与阻塞

- 面板/对话流尚未接入 app.py 前端展示层与停止按钮 wiring（需 UI 侧配合，属主路径集成，GOAL 第 11 节汇报时标注）。
- 辅助功能与键盘交互回归需真实客户端环境，本机联合验收（G11）记录为阻塞项。

### Git diff 摘要

```text
?? task_panel.py / conversation_stream.py / tests/technical_platform/test_unified_events.py
git diff --check: 干净
```

未提交、未推送。

---

## G10：诊断、隐私和故障演练 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

诊断 Trace 覆盖 task/turn/plan/node/attempt ID、渠道状态、首响应延迟、重试原因、manifest ID、Skill/规则/模板哈希、资源等待、Office/WPS 选择、浏览器 origin、服务端 job ID、计费状态、产物 ID/哈希/验证状态；客户端不显示 Token 和费用；诊断包默认排除文档正文、密码、Cookie、API Key 和完整客户路径，导出前可预览；12 个故障演练场景全部有明确终态、恢复策略和用户可理解提示；敏感信息扫描 0 命中。

### 开工前事实

- G07 `workflow_runtime.py`（RETRYABLE/NON_RETRYABLE/崩溃语义/cancel）、`workflow_reconciliation.py`（reconcile_unknown 三态决策）、`workflow_journal.py`（落盘恢复）已逐行核验，演练直接驱动这些真实路径。

### 测试先行证据

- `test_diagnostic_bundle.py`（13 项）与 `test_failure_drills.py`（16 项）先于实现落盘，首轮 29 failed（模块不存在）。

### 失败测试与根因

- 实现后 1 项失败：`test_export_refuses_sensitive_bundle` 设计与实现重叠——build_bundle 已脱敏 notes，导出拒绝路径永不可达；修正测试为绕过 build_bundle 直接构造脏 bundle，验证 export_bundle 独立防线生效。实现语义未变。
- 静态检查：15 项风格问题（I001/F401/C408 等）由 ruff --fix --unsafe-fixes 修复后复跑全绿。

### 修改文件（未提交）

- 新增 `diagnostic_bundle.py`（`DiagnosticTrace` 全字段 frozen strict，Token/费用无字段可走私（extra=forbid 实测拒绝）；`SENSITIVE_PATTERNS` 五类（password/cookie/api_key/bearer/client_path）；`redact_text/scan_sensitive`；`build_bundle` 丢弃文档正文键（content/body/document_text/full_text）并脱敏事件 payload 与 notes；`preview_bundle` 导出前预览；`export_bundle` 扫描命中即拒绝且不写文件）
- 新增 `failure_drills.py`（`SCENARIOS` 12 场景；`DrillOutcome`：terminal_state∈{failed,cancelled,recovered,manual_review,rejected,waiting} + recovery + user_message + evidence；断网/超时/余额不足/文件占用真实驱动 WorkflowRuntime（重试与不重试语义有 Journal 证据）；响应丢失走 reconcile_unknown（charged→recovered 不重复扣费 / 无记录→manual_review）；客户端重启验证已提交节点不重复执行（s1_calls=0 断言）；Office 崩溃/页面变化→manual_review 不重放；WPS 不可用→Office 回退或无后端明确失败；Skill 冲突哈希比对拒绝；损坏 ZIP BadZipFile 拒绝；取消经真实 cancel 事件且执行器零调用）
- 新增 `tests/technical_platform/test_diagnostic_bundle.py`（13 项）、`tests/technical_platform/test_failure_drills.py`（16 项）
- 本账本

### 关键设计决定

- 导出拒绝是独立最后一道防线：不依赖 build_bundle 的脱敏覆盖率，任何来源的 bundle 扫描命中即拒。
- 余额不足定义为 NON_RETRYABLE 业务故障（InsufficientBalanceError(ValueError)），永不自动重试扣费请求。
- 文件占用按 PermissionError→failed+恢复指引演练（运行时的 node_waiting_resource 等待路径已由 G07/G09 测试覆盖）。

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| `pytest test_diagnostic_bundle.py + test_failure_drills.py` | **29 passed** |
| 邻域回归（workflow_runtime/workflow_plan/unified_events/skill_installation 4 文件） | **58 passed** |
| 全量第 3 批（重建后 176 文件清单，含 2 个新测试文件） | **381 passed, 0 failed** |
| `ruff check`（2 新模块 + 2 测试） | All checks passed |
| `mypy`（2 新模块） | 自身 0 error |

### 回归风险

- 纯新增模块，无既有调用方改动。

### 未完成项与阻塞

- 诊断包导出 UI 入口与预览弹窗属前端集成，随 G11 汇报标注。
- 真实环境演练（真实断网/真实 Office 崩溃/WPS-only 机器）写入 G11 阻塞项。

### Git diff 摘要

```text
?? diagnostic_bundle.py / failure_drills.py / tests/technical_platform/test_diagnostic_bundle.py / tests/technical_platform/test_failure_drills.py
git diff --check: 干净
```

未提交、未推送。

---

## G11：本机联合验收、构建与发布准备 — VERIFIED

- 开始：2026-09-18 · 完成：2026-09-18

### 目标

第 8 节全量测试真实运行；构建新的本机验收 EXE 到新的 D 盘时间戳目录（不覆盖旧验收包）；冻结包冒烟与内置 Skill 证明；冻结包敏感扫描；只完成本地候选包、哈希、文件清单、回归报告和发布建议，未授权事项一律不执行；无环境项写为明确阻塞。

### 开工前事实

- `dist/technical_platform` 存在旧验收包（不得覆盖）；`build_technical_platform.py` 输出路径硬编码；`smoke_technical_platform_exe.py` 的 dist 路径硬编码但健康检查/规则比对仍以仓库 ROOT 为准。
- 根目录 3 个测试文件收集期报错（import 缺失的 `test_detail_workbook_pipeline_guards`，git 历史从未存在），确认为开工前既有问题。

### 失败与根因

- 首次构建 Bash 命令中 `\\$TS` 转义使 `$TS` 未展开，产物落入字面目录 `acceptance-builds$TS`；且 300s 前台超时在更新器构建中段终止（主 EXE 已完成）。处理：目录改名为 `acceptance-builds/20260918-223356`，两个 bootstrap EXE 按脚本同等参数单独补建（图标用绝对路径）。
- 冻结包扫描命中 2 个 sqlite：冒烟以冻结目录为 cwd 启动客户端后，客户端从旧安装迁移本地设置（owner 哈希+本机项目路径），属禁含的用户账号缓存。已从候选包移除并复扫 0 命中；内容已逐行检查无凭据。

### 修改文件（未提交）

- 修改 `scripts/build_technical_platform.py`（新增 `TP_DIST_ROOT`/`TP_BUILD_WORK` 环境变量重定向，默认行为不变；26 个 G02–G10 新模块登记 hidden-import）
- 修改 `scripts/smoke_technical_platform_exe.py`（新增 `TP_SMOKE_DIST` 环境变量指定被测冻结目录，默认行为不变）
- 新增 `D:\ZQ-Acceptance\acceptance-builds\20260918-223356\ACCEPTANCE-RECORD.md` 与 `file-manifest.json`
- 本账本

### 测试命令与结果（真实运行）

| 套件 | 结果 |
|---|---|
| 全量发现 `pytest --collect-only -q` | 1738 collected, 3 既有收集错误 |
| tests/technical_platform（4 批） | **1182 passed** |
| tests/report_review_app | **227 passed** |
| tests/report_review_server | **207 passed, 1 skipped**（PostgreSQL 并发需独立 PG URL） |
| tests/agent_acceptance + platform_update | **104 passed** |
| tests/ 根目录 4 文件 | **17 passed** |
| 合计 | **1737 passed, 1 skipped, 3 既有收集错误** |
| `build_technical_platform.py`（TP_DIST_ROOT 重定向） | 主 EXE + 更新器 + 启动器全部构建成功 |
| `smoke_technical_platform_exe.py`（TP_SMOKE_DIST） | **PASS**（健康检查/规则字节一致/登录窗口，client=0.2.10, schema=11） |
| `prove_local_builtin_skills.py` | financial_ok=true, workflow_ok=true |
| 冻结包文件名敏感扫描 | 移除 2 个冒烟泄漏 sqlite 后 **0 命中** |
| 新模块入包核对（PYZ-00.toc） | 26/26 在包 |
| `git diff --check` | 干净 |

### 构建产物

- `D:\ZQ-Acceptance\acceptance-builds\20260918-223356\dist\technical_platform\ZQ技术平台\ZQ技术平台.exe`（16,604,448 B，SHA256 6a82753e…4549c0）；更新器/启动器 SHA256 见 ACCEPTANCE-RECORD.md；文件清单 4731 项。

### 回归风险

- 构建/冒烟脚本改动为纯增量环境变量覆盖，默认值与原行为完全一致。
- 新模块随包分发但未接入 app.py 主路径（G09 已标注），不改变现有客户端行为。

### 未完成项与阻塞（明确阻塞，不虚报）

- 干净 Windows 全新安装；仅 Office/仅 WPS/Office+WPS 矩阵；历史版本无损升级与失败回退；真实 OA 验证码与业务回执；Authenticode 正式签名。
- 新 Harness 接入客户端主执行路径（UI wiring）属后续工作。

### Git diff 摘要

```text
 M scripts/build_technical_platform.py / scripts/smoke_technical_platform_exe.py
?? （构建产物在工作树外 D:\ZQ-Acceptance\acceptance-builds\20260918-223356\）
git diff --check: 干净
```

未提交、未推送、未部署、未发布、未调用真实付费模型。

### G11 后续修复（2026-09-19，本地提交）

- 问题：冒烟以冻结目录为 cwd 启动客户端时，首启迁移把本地设置 sqlite 写入冻结目录（用户账号缓存类禁含物）。
- 根因与方案更正：首版尝试用 `ZQ_INSTALLATION_ROOT` 重定向，触发托管安装锁校验（installation-lock.sqlite 缺失）失败；最终方案为 `app.py` 新增 `ZQ_SETTINGS_ROOT` 环境变量（仅设置数据重定向，默认行为不变，不破坏"平台数据不默认写 C 盘"红线），冒烟脚本登录窗口启动改用它指向 `build/packaged-health-smoke/launch-data`。
- 验证：新候选包 `D:\ZQ-Acceptance\acceptance-builds\20260919-042141\` 重建后主 EXE SHA256 `d04f7613…5a3b30`，冒烟 PASS，冒烟后冻结包扫描 0 命中，设置确认落在隔离目录；邻域回归 331 passed + 技术平台第 1 批 227 passed；ruff 通过。
- 新候选取代 20260918-223356；两个旧包均未覆盖。

### G11 后续增强（2026-09-19，本地提交）：澄清上下文压缩接入主路径

- 目标：把 G03 已验证的 conversation_compactor 接入 agent_controller 主执行路径，带预算压缩替代全量历史。
- 现状核验发现：UnderstandingRequest.context 已有硬边界（≤10 条、整包 ≤64KB、MessageRef extra=forbid 无 summary 字段）；主路径唯一无界增长点是多轮澄清的存储上下文；build_manifest 因 UnderstandingRequest 契约无 manifest 字段，本次不接（需契约扩展，留后续）。
- 实现：新增 `context_assembly.py`（compact_clarification_context：PREFIX 分支参考逐字透传且永不入摘要，其余折叠为带"非原始证据"标记与内联回查 id 的摘要，近 4 轮逐字保留）；`agent_controller.complete()` ask 路径先校验、超界再压缩、仍超界才 ClarificationContextLimit；提取 `_validate_next_exchange`。
- 既有测试契约更新（透明记录）：`test_clarification_overflow_does_not_silently_drop_original_constraints` 原断言"超界必须拒绝"，与新批准的压缩特性直接冲突；已更新为更强形式的不变式——原始限制逐字保留在会话存储 + 摘要带标记可回查 + 压缩后请求合法；硬拒绝路径由新测试 monkeypatch 压缩无效场景确定性覆盖。
- 测试：新增 `test_context_compaction_wiring.py`（8 项，先行首轮 7 failed）；专项 8 passed；邻域 120 passed；批次 227+380 passed；ruff/mypy 干净。
- 未完成：build_manifest 接入需 UnderstandingRequest 契约扩展；冻结包未含本增强（下次构建随包）。
