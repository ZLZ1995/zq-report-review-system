# Kimi Work：ZQ 技术平台 Agent / Harness 全量优化执行目标

> 文件性质：可直接交给 Kimi Work 执行的总目标文件。  
> 制定日期：2026-09-18（Asia/Shanghai）。  
> 施工入口：`D:\ZQ-Acceptance\local-feature-checkout`。  
> 当前分支：`codex/local-platform-feature-update`。  
> 基线提交：`d1276a680354edf02ee5d43254d934b4f7863f27`。  
> 本文件只授权本地源码修改、测试、构建和验收；不自动授权推送 GitHub、部署 Zeabur、激活稳定发布、使用付费模型或处理真实客户资料。

---

## 0. 给 Kimi Work 的直接执行命令

你现在负责在现有 ZQ 技术平台上完成 Agent、Harness、上下文、记忆、Skill、任务恢复和对话式进度的系统性优化。

请完整读取本文件以及第 1 节列出的全部必读资料，随后从 G00 开始，严格按照 G00→G11 顺序持续施工。每一阶段均执行：

```text
现状核验 → 最小设计 → 测试先行 → 增量实现 → 专项测试
→ 邻域回归 → 静态检查 → 记录证据 → 阶段复查 → 自动进入下一阶段
```

除非出现第 4 节定义的真实阻塞，不要等待用户重复发送“继续”，不要跳过失败测试，不要以“代码看起来正确”代替运行验证。发现既有实现已经满足要求时，必须用代码位置和测试证据证明，不要重复重写。

最终目标不是简单增加几个类，而是形成以下可信执行链：

```text
用户自然语言与本轮附件
  → TurnEnvelope 不可变快照
  → 结构化意图理解
  → 能力检索与 Skill 路由
  → 声明式 WorkflowPlan 编译
  → 权限、预算与资源决策
  → 可取消、可恢复、可对账的 Harness
  → 白名单 Skill / Office / 浏览器 / 模型适配器
  → 独立验证
  → 对话流式交付
  → 受控记忆候选与 Skill 反馈
```

---

## 1. 开工前必须完整读取

按顺序完整读取，不允许只看摘要：

1. `docs/technical_platform/KIMI_CODE_HANDOFF.md`
2. `docs/technical_platform/AGENT_HARNESS_OPTIMIZATION_PLAN_CC_HAHA.md`
3. `docs/technical_platform/GOAL_INTEGRATED_DELIVERY_CHECKLIST.md`
4. `docs/technical_platform/LOCAL_FEATURE_UPDATE_CHECKLIST.md`
5. 仓库根目录 `AGENTS.md` 和 `CONTEXT.md`（如存在）
6. 当前 Git 状态及全部未提交改动
7. `.codex/skills/` 下与本任务相关的 `SKILL.md`
8. 以下核心实现：
   - `src/asset_based_agent/technical_platform/agent_controller.py`
   - `src/asset_based_agent/technical_platform/planner.py`
   - `src/asset_based_agent/technical_platform/harness.py`
   - `src/asset_based_agent/technical_platform/context.py`
   - `src/asset_based_agent/technical_platform/memory_service.py`
   - `src/asset_based_agent/technical_platform/memory_retrieval.py`
   - `src/asset_based_agent/technical_platform/capability_registry.py`
   - `src/asset_based_agent/technical_platform/task_manager.py`
   - `src/asset_based_agent/technical_platform/execution.py`
   - `src/asset_based_agent/technical_platform/routing.py`
   - `src/asset_based_agent/technical_platform/permissions.py`
   - `src/asset_based_agent/technical_platform/agent_permission_modes.py`
   - `src/asset_based_agent/technical_platform/tool_dispatcher.py`
   - `src/asset_based_agent/agent_contracts.py`
9. `tests/technical_platform/` 中上述模块的现有测试。

若文档与实现冲突，按以下优先级裁决并记录差异：

```text
用户已确认的业务红线
  > 当前有效 Skill 和锁定模板契约
  > 可运行测试与数据库迁移
  > 当前代码
  > 最新执行账本
  > 历史设计文档
```

---

## 2. 施工环境和工作区保护

### 2.1 唯一施工入口

- 权威工作树：`D:\ZQ-Acceptance\local-feature-checkout`
- 共用虚拟环境：`D:\1\1\ai-excel-agent\.venv`
- Python：使用上述虚拟环境中的 Python 3.10.11。
- `D:\1\1\ai-excel-agent` 是历史目录，不是本轮权威源码入口。

### 2.2 当前工作区是用户资产

当前工作区包含大量已修改文件、未跟踪文件、两项新 Skill 和尚未发布的本地功能。必须全部保留。

禁止：

- `git reset --hard`
- `git checkout -- .`
- `git clean -fd`
- 强制切换分支覆盖文件
- 强推
- 用远端重新检出替换当前工作区
- 未检查内容就执行 `git add .`
- 删除或回滚不属于本任务的改动

G00 必须先保存：

```text
git status --short
git diff --stat
git diff --name-status
git ls-files --others --exclude-standard
git rev-parse HEAD
git branch --show-current
```

将结果写入执行账本。可生成只读补丁备份，但备份必须写到明确的 D 盘临时目录，不得覆盖源码。

### 2.3 中文 Windows 规则

- 中文路径、文件名、Sheet 名、参数和输出禁止使用 PowerShell。
- 优先 WSL/bash，其次 Git Bash，再其次 cmd。
- 不要通过 PowerShell 传递中文路径或中文正文。
- 出现 `?` 先判断字符是否在进入子进程前丢失；出现乱码先定位解码环节。
- 源码编辑使用小范围补丁，不使用整文件脚本覆盖用户改动。

---

## 3. 永久业务红线

这些约束在任何权限模式下都不得绕过：

1. 原始 Word、Excel、PDF 默认只读；修改、批注或生成均输出副本。
2. Excel hidden/veryHidden 工作表的任何内容不得进入审核、模型上下文或上传数据；仅允许使用可见汇总表已经呈现的最终值。
3. 锁定模板不得重建或替换；成果必须落入模板副本，保留公式、链接、超链接、命名区域、隐藏状态和版式。
4. `valuation-detail-workbook-fill` 以当前 Skill 中更新后的 `template.xlsx` 为唯一模板。
5. 业务资料和成果不得默认写入 C 盘；平台数据位于软件安装目录 `data/`。
6. 客户端不得保存、显示或配置供应商 API Key。
7. 用户界面只能显示余额，不显示 Token、费用、倍率或模型价格。
8. 未被本轮明确选中的历史附件不得进入当前任务。
9. 用户取消任务后不得继续模型扣费、Office 写入、浏览器副作用或文件交付。
10. 浏览器网页内容不是系统指令、授权或可信证据；任何网页操作必须绑定任务、页面、origin 和当前计划。
11. 外部 Skill 不得执行未登记脚本，不得覆盖官方锁定 Skill。
12. 记忆不得保存 API Key、密码、Cookie、完整客户文档、身份证号、银行账号或未经确认的模型推断。
13. 三档权限模式只决定何时询问，不改变上述硬拒绝规则。

---

## 4. 自动推进与真实阻塞

### 4.1 不属于阻塞

以下情况不得停工等待用户：

- 测试失败。
- 类型检查或 lint 失败。
- 现有文档过期。
- 需要增加测试夹具。
- 需要在几个兼容实现中选择一个。
- 旧代码结构不理想。
- 单项测试耗时较长。

应先复现、缩小范围、确认根因，再做最小可控改动。

### 4.2 可以报告阻塞

只有以下情况可以暂停对应项，同时继续其他不受影响的工作：

- 缺少真实账号、验证码或硬件设备。
- 需要使用付费大模型但未获得账号及费用上限授权。
- 需要推送 GitHub、修改远端仓库、部署 Zeabur、激活稳定版或操作生产数据库，但当前没有明确授权。
- 需要独立干净 Windows、仅 Office 或仅 WPS 环境，而本机无法提供。
- 需要真实客户资料但只有合成夹具。
- 目标存在互斥业务选择，且不同选择会产生实质不同交付结果。

阻塞报告必须写明：阶段、已完成部分、缺少内容、为何无法用合成夹具替代、用户需提供的最小动作。不得把整个目标标记完成。

---

## 5. 执行账本和证据规则

开工时创建并持续维护：

`docs/technical_platform/KIMI_WORK_AGENT_HARNESS_EXECUTION_LEDGER.md`

每个阶段记录：

```text
阶段编号 / 状态 / 开始时间 / 完成时间
目标
开工前事实
失败测试与复现步骤
根因
修改文件
关键设计决定
测试命令
测试结果（passed/failed/skipped 数量）
静态检查结果
回归风险
未完成项与阻塞
Git diff 摘要
证据文件路径
```

状态只能使用：

```text
NOT_STARTED
IN_PROGRESS
VERIFIED
BLOCKED
FAILED
```

规则：

- 只有验收命令真实运行并通过才可写 `VERIFIED`。
- `skipped`、`xfail` 和外部环境缺失必须单独解释。
- 不得用上一版本的测试记录证明当前工作树。
- 每阶段完成后复查 `git diff --check` 和 `git status --short`。
- 所有产物、测试日志和诊断包不得包含明文凭据或客户正文。

---

## 6. 通用施工纪律

1. 测试先行：先写能稳定复现问题的最小失败测试。
2. 小步迁移：现有 `harness.py`、`agent_controller.py`、`context.py`、`memory_service.py` 不一次性推倒重写。
3. 兼容适配：先引入新契约和适配层，新旧回归等价后再删除旧入口。
4. 模型不拥有最终执行权：模型只能提出结构化意图或计划；本地编译器验证并映射到白名单 Adapter。
5. 不执行模型生成代码：工作流使用声明式节点，不使用 `eval`、`exec` 或动态下载执行。
6. 事实可追溯：关键决定绑定 turn、文件版本、Skill 版本、规则哈希和证据 ID。
7. 简单任务不强制多 Agent；只有并行、上下文、独立验证确有收益时才拆分。
8. 执行与验证分离；Verifier 不得修改成果。
9. UI 只提交命令和显示事件，不直接执行 Agent、Office、浏览器或模型动作。
10. 网络/服务端响应未知时先对账，不直接重发可能扣费的请求。

---

## 7. G00—G11 全量施工清单

### G00：基线冻结、上下文入口和 ADR

目标：让后续施工建立在真实代码而非历史描述上。

实施：

- 采集第 2.2 节基线证据。
- 运行现有技术平台基线测试，记录通过、失败、跳过数量。
- 新建或更新根目录 `CONTEXT.md`，至少覆盖项目定位、红线、目录、主链路、任务类型、Skill层级、Harness、调试原则和文档分工。
- 建立 `docs/adr/`，至少新增：
  - Agent 分层与本地可信边界。
  - TurnEnvelope 与附件范围。
  - Context Manifest 与Token预算。
  - 记忆治理。
  - Skill Contract v2。
  - 声明式 Workflow Harness。
  - 权限模式与硬拒绝规则。
- ADR 使用“背景、决定、替代方案、后果、验收”格式。

验收：

- 新 Agent 在 5 分钟内可由 `CONTEXT.md` 定位主链路。
- 文档不包含项目实例事实和明文凭据。
- 基线测试结果进入账本。
- 未改动或覆盖用户既有本地功能。

### G01：TurnEnvelope 和输入网关

目标：彻底消除历史附件串入、范围漂移和迟到结果覆盖。

建议新增：

- `turn_context.py`
- `turn_normalizer.py`
- `turn_scope_policy.py`
- `input_gateway.py`
- `tests/technical_platform/test_turn_context.py`

最低字段：

```text
schema_version
owner / project_id / session_id / turn_id / message_id
raw_user_text / normalized_text
explicit_references[]
selected_attachment_versions[]
newly_attached_ids[]
historical_reference_ids[]
excluded_attachment_ids[]
active_model_id / permission_mode
browser_page_identity（如适用）
locale / timezone / submitted_at
prior_clarification_chain[]
content_hash
```

实施：

- UI提交消息时一次性生成不可变 envelope。
- 理解、规划、执行、恢复只传 envelope ID/hash，不重新扫描会话全部附件。
- 附件替换、删除、会话切换、权限或模型变化使旧理解结果失效。
- 当前轮明确提到的文件名与选中附件不一致时进入澄清。
- UI展示“本轮资料范围”摘要。

验收至少覆盖40项：新/旧附件、只处理指定文件、排除文件、同名不同版本、替换、删除、重命名、分支继承、会话切换、迟到结果、取消后恢复。未选历史附件进入任务必须为0。

### G02：自然语言理解 v2

目标：先理解目标、对象、排除项和交付形式，再检索能力。

建议新增：

- `intent_schema.py`
- `intent_policy.py`
- `tests/technical_platform/fixtures/intent_eval_zh.jsonl`
- `tests/technical_platform/test_intent_understanding_v2.py`

实现四阶段：

1. 确定性预解析：动作、文件名、数量、时间指示、否定、条件、例外、交付格式、取消和授权。
2. 模型结构化理解：严格返回 intent、goal、targets、references、excluded_inputs、deliverables、constraints、assumptions、required_capabilities、risk_flags、ambiguities、next_action。
3. 本地裁决：对象必须来自 TurnEnvelope；业务红线高于模型；冲突进入澄清。
4. 最小澄清：只有会改变计划或成果的问题才询问。

建立不少于120条中文评估集，必须包含口语、错别字、省略、连续要求、否定、双重否定、条件句、跨Skill任务、用户纠正、资料不全、浏览器组合、Skill ZIP 和纯问答。

验收：

- 目标/参考/排除文件准确率100%。
- 高风险动作漏澄清0。
- 错误Skill实际执行0。
- 不必要澄清率低于10%。
- 模型不可直接授予工具权限。

### G03：Context Manifest、证据检索和预算

目标：每次模型调用的上下文可解释、可复现、可裁剪。

建议新增：

- `context_manifest.py`
- `context_budget.py`
- `conversation_compactor.py`
- `evidence_retriever.py`
- 对应测试。

实施：

- 每次模型调用保存脱敏 manifest：系统策略哈希、TurnEnvelope哈希、Skill版本/规则哈希、记忆ID、摘要ID、证据片段ID、工具回执ID和各部分预算。
- 从字符数裁剪升级为Token估算。
- 固定保留系统红线、本轮范围和选中Skill契约。
- 文件证据按目标高于参考排序。
- 相关长期记忆最多5条。
- 工具大输出落盘，只按ID引用。
- 摘要标记“非原始证据”，最终判断回查原片段。
- Excel证据入口再次验证hidden/veryHidden过滤。

验收：

- 同一输入生成稳定manifest。
- 隐藏表片段进入manifest为0。
- 本轮范围和业务红线永不被裁剪。
- 长会话Token显著下降，既有审核召回率不下降。
- 用户诊断视图可说明使用了哪些来源，但不泄露系统提示词、价格、Token或密钥。

### G04：记忆架构 v2

目标：形成有来源、有生命周期、可撤销且不会污染业务事实的记忆。

建议新增：

- `memory_candidates.py`
- `memory_selector.py`
- `memory_consolidation.py`
- `tests/technical_platform/test_memory_candidates.py`
- `tests/technical_platform/test_memory_retrieval_v2.py`

分为：

- 协作记忆：user、feedback、project、reference。
- 运行记忆：摘要、未完成任务、澄清链、回执。
- Skill学习：误判、漏判、用户验收标签和修正规则建议。

记录状态：proposed、confirmed、revoked、superseded。记录来源消息/任务、版本、有效期、敏感级别、可信度、验证策略和最后验证时间。

实施：

- 主回复结束且无活动工具时仅对新增消息抽取候选。
- 用户纠正和明确偏好可建议记住；项目事实必须确认。
- 写入前去重、冲突、敏感扫描。
- 召回最多5条并带陈旧提示。
- 当前文件证据优先于记忆。
- 提供本轮忽略、查看来源、撤销和删除项目记忆。

验收：敏感样本写入率0；未经确认的项目事实不影响执行；撤销后不再召回；冲突记忆不会覆盖当前证据。

### G05：Skill Contract v2 和基础能力

目标：Skill可检索、组合、验证、安全安装和更新。

扩展机读契约：

```text
id / name / version / source / trust_level
description / when_to_use / when_not_to_use
positive_examples[] / negative_examples[]
input_roles[] / required_inputs[] / optional_inputs[]
supported_extensions[] / output_types[]
allowed_tools[] / network_policy / modifies_originals
template_locks[] / resource_locks[]
model_policy / token_budget
acceptance_gates[] / feedback_schema
compatibility / migration
```

来源优先级：官方锁定/managed > 官方签名更新 > 项目 > 用户外部 > 远程临时能力。冲突不得静默覆盖。

补齐或正式化以下基础能力：

1. `material-classifier`
2. `turn-scope-resolver`
3. `office-runtime-preflight`
4. `document-evidence-indexer`
5. `spreadsheet-formula-auditor`
6. `document-layout-verifier`
7. `artifact-integrity-verifier`
8. `task-reconciliation`
9. `provider-diagnostics`
10. `browser-receipt-verifier`
11. `memory-curator`
12. `skill-lint-and-eval`

这些是后台基础能力，不恢复用户手动切换Skill的旧交互。

验收：

- 每个正式Skill有正反例、输入角色和最小验收集。
- 同ID冲突不静默覆盖。
- 锁定模板只能由可信官方版本更新。
- 外部ZIP无法路径穿越、执行未知脚本或读取平台密钥。
- 两项当前本地新Skill及既有业务Skill均能被自然语言正确路由。

### G06：声明式 WorkflowPlan 和编译器

目标：模型只提出计划，本地可信编译器决定能否执行。

建议新增：

- `workflow_plan.py`
- `workflow_compiler.py`
- `tests/technical_platform/test_workflow_plan.py`

只允许节点：

```text
understand
classify_materials
extract_evidence
model_call
run_skill
browser_action
validate_artifact
verify_business_result
ask_user
deliver
```

实施：

- 编译器验证节点类型、依赖、输入来源、输出契约、权限、预算、资源锁、Skill版本和适配器。
- 拒绝循环、孤立交付、未知工具、未选附件、跨项目路径和原件写入。
- 计划修订保留revision和差异原因。
- 旧planner输出通过兼容适配层转换，回归等价后再迁移。

验收：恶意/错误计划均被本地拒绝；模型文本不能变成任意代码；同一输入编译结果稳定；旧审核和生成任务保持可用。

### G07：Workflow Harness v2

目标：支持多阶段、资源调度、取消、恢复、幂等和未知状态对账。

建议新增：

- `workflow_runtime.py`
- `workflow_journal.py`
- `workflow_scheduler.py`
- `workflow_events.py`
- `workflow_reconciliation.py`
- 对应测试。

实施：

- DAG就绪队列和可控并行。
- Office/WPS、工作簿、输出目录、浏览器页面、模型渠道资源锁。
- 调用次数、Token预估、余额冻结、文件数、时间预算。
- 每节点超时、有限重试、退避和不可重试分类。
- 父子取消树，确保释放进程、COM、浏览器租约和文件锁。
- 追加式Journal：run_created、node_claimed、node_progress、node_result_committed、node_failed、permission、resource、artifact、run_terminal。
- 缓存键包含计划版本、节点、适配器、输入哈希、Skill版本、规则哈希、权限快照和依赖结果。
- 模型任务unknown先按client_job_id对账；Office和浏览器写动作unknown不得自动重放。

验收：

- 进程中断恢复不重复扣费。
- 同一Office/输出目录无并发写。
- 取消后无僵尸Worker和外部副作用。
- unknown进入reconciliation，不盲目重放。
- 既有本地生成、报告审核和浏览器任务全部兼容。

### G08：专用 Agent Profiles 与独立验证

目标：按角色限制上下文和工具，执行与验收分离。

建议新增：

- `agent_profiles.py`
- `tests/technical_platform/test_agent_profiles.py`

角色：Conversation、Intent Analyst、Capability Router、Plan Compiler、Domain Executor、Independent Verifier、Memory Curator、Browser Operator。

实施：

- 每个Profile明确可读上下文、允许工具、禁止数据、模型策略、输出schema和预算。
- Verifier只读成果及必要证据，不得修改成果。
- Browser Operator绑定页面租约、origin和任务，不读取凭据明文。
- Memory Curator无业务文件写权限。
- 仅在文件组并行、独立验证、多成果或上下文超限时拆Agent。

验收：简单任务不额外拆Agent；复杂任务可控并行；故意制造的公式、版式、哈希、模板和回执错误均由Verifier拦截。

### G09：统一事件、对话流式交付和任务面板

目标：用户在对话中看到真实阶段、输出和成果，不再看到无解释的假进度。

统一事件：

```text
phase_started / phase_completed
node_queued / node_started / node_progress
node_waiting_resource / node_waiting_user
node_retrying / node_succeeded / node_failed
artifact_ready / task_completed
```

实施：

- 模型增量、解析状态、Office处理、浏览器动作、验证、上传和交付进入同一对话流。
- 显示阶段、当前节点、完成数/总数、等待原因、最近活动时间和可取消状态。
- 百分比只作辅助，不能长期停在无法解释的60%。
- 重启后根据Journal恢复同一任务状态。
- 不恢复独立“成果”栏；成果文件以对话链接和任务详情呈现。

验收：所有长阶段持续有真实事件或明确等待原因；停止按钮可用；恢复后不复制消息或成果；辅助功能和键盘交互回归通过。

### G10：诊断、隐私和故障演练

目标：错误可定位，诊断不泄露客户资料和凭据。

建议新增：

- `diagnostic_bundle.py`
- 诊断导出测试和脱敏测试。

Trace至少包含：task/turn/plan/node/attempt ID、渠道状态、首响应延迟、重试原因、manifest ID、Skill/规则/模板哈希、资源等待、Office/WPS选择、浏览器origin、服务端job ID、计费状态、产物ID/哈希/验证状态。

客户端不得显示Token和费用。诊断包默认排除文档正文、密码、Cookie、API Key和完整客户路径；导出前允许预览。

演练：断网、余额不足、模型超时、响应丢失、客户端重启、Office崩溃、WPS不可用、文件被占用、浏览器页面变化、用户取消、Skill冲突和损坏ZIP。

验收：所有演练有明确终态、恢复策略和用户可理解提示；敏感信息扫描为0命中。

### G11：本机联合验收、构建与发布准备

目标：证明优化后的客户端在本机达到可交付候选状态。

本机验收矩阵：

- 报告审核首轮/多轮、忽略、建议、批注副本和标准Word审核报告。
- 当前轮新附件不夹带历史文件。
- 隐藏表内容不上传。
- 评估明细表锁定模板、公式、链接和万元单位。
- 工商历史沿革字体、字号和缩进。
- 财务简报。
- Office工作流转Skill。
- 外部Skill ZIP自然语言安装、冲突和拒绝。
- 三档权限模式与硬拒绝。
- 浏览器外网、OA合成文件上传、下载和回执（有账号/验证码时）。
- 断网、取消、恢复、模型响应丢失和重复请求。
- 平台数据和业务成果不默认写入C盘。

必须运行第 8 节测试，构建新的本地验收EXE，并执行冻结包冒烟。构建目录使用新的D盘时间戳目录，不覆盖旧验收包。

本阶段默认只完成本地候选包、哈希、文件清单、回归报告和发布建议。没有用户明确授权时：

- 不提交或推送GitHub。
- 不部署Zeabur。
- 不创建或激活公开Release。
- 不调用真实付费模型。

干净Windows、仅Office、仅WPS和历史无损升级若无环境，写为明确阻塞，不得虚报通过。

---

## 8. 验证命令

在 `D:\ZQ-Acceptance\local-feature-checkout` 使用 cmd 执行。先设置：

```bat
set PYTHONPATH=src
```

### 8.1 每阶段专项测试

只运行与改动直接相关的测试文件，并记录完整命令和结果。新增模块必须有对应测试。

### 8.2 技术平台完整回归

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\technical_platform -q
```

### 8.3 报告审核客户端回归

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_app -q
```

### 8.4 服务端回归

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest tests\report_review_server -q
```

### 8.5 全量测试发现

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m pytest --collect-only -q
```

然后根据项目现有分组执行完整回归，不得把“只收集成功”当测试通过。

### 8.6 静态检查

对本阶段全部修改文件运行 Ruff；对新Agent/Harness核心模块运行Mypy。既有类型债务与本轮新增错误要分开记录，不得为了清零而大范围修改无关模块。

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m ruff check <本阶段修改文件>
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe -m mypy <本阶段核心模块>
git diff --check
```

### 8.7 构建和本机证明

```bat
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\build_technical_platform.py
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\smoke_technical_platform_exe.py
D:\1\1\ai-excel-agent\.venv\Scripts\python.exe scripts\prove_local_builtin_skills.py
```

打包前检查冻结目录中不得包含：

```text
*.db / *.sqlite / *.log / .env
用户账号缓存
浏览器Cookies和密码
API Key和JWT密钥
客户原始资料
任务诊断正文
发布私钥
```

---

## 9. 必须保留的兼容行为

优化不得破坏：

- 登录先于工作台，服务地址内置。
- 账号单设备会话和余额预检。
- 项目改名、置顶、归档、恢复和移除菜单。
- 项目下多会话/分支。
- 回车发送、Alt+回车换行。
- 文件拖拽和当前轮附件隔离。
- 自动Skill路由，不恢复手动Skill选择器。
- 浏览器独立面板、多标签、书签、下载和DPAPI账号保存。
- 浏览器可以由用户或Agent调用，不与OA强绑定。
- 三档全平台权限模式。
- 报告审核只读、隐藏表过滤、多轮问题状态和批注副本询问。
- 两项本地新Skill以及现有锁定模板。
- 在线更新、签名校验和失败回退现有能力。
- 服务端review-jobs、计费幂等和模型渠道机制。

---

## 10. 总体验收门槛

以下全部满足，才可将本地工程标记为“可交付候选”：

| 指标 | 目标 |
|---|---:|
| 未选历史附件进入任务 | 0 |
| 隐藏/veryHidden内容进入模型上下文 | 0 |
| 原始业务文件被修改 | 0 |
| 同一远程任务重复扣费 | 0 |
| 高风险意图未澄清即执行 | 0 |
| 自然语言错误Skill实际执行 | 0 |
| 用户取消后继续外部副作用 | 0 |
| 敏感信息写入记忆或诊断包 | 0 |
| 外部Skill覆盖锁定官方Skill | 0 |
| 简单任务无必要拆多Agent | 0 |
| 任务阶段和等待原因可解释率 | 100% |
| 成果具备来源、版本、哈希和验证状态 | 100% |
| 技术平台完整测试 | 全部通过；跳过项逐项解释 |
| 客户端/服务端邻域回归 | 全部通过 |
| 新EXE冻结包冒烟 | 通过 |

以下不能被本机结果替代：

- 干净Windows全新安装。
- 仅Office、仅WPS、Office+WPS矩阵。
- 历史版本无损升级和失败回退。
- 真实OA验证码和业务成功回执。
- 正式Windows Authenticode签名。

缺少这些环境时，最终状态应为“本机可交付候选；外部环境验收待完成”，不能写“正式发布完成”。

---

## 11. 最终交付物

Kimi Work 完成后必须交付：

1. 全部源码和测试改动。
2. `CONTEXT.md` 和ADR。
3. 持续更新的执行账本。
4. 中文自然语言理解评估集及结果。
5. TurnEnvelope、Context Manifest、Memory v2、Skill Contract v2、WorkflowPlan/Harness v2 的开发文档。
6. 全量测试、Ruff、Mypy和`git diff --check`记录。
7. 本机验收EXE、SHA256、文件清单和冻结包扫描结果。
8. 已知限制、外部环境阻塞和回归风险清单。
9. Git变更清单，区分：本次新增、开工前已有、未触碰的用户改动。
10. 发布建议，但在未授权时不执行远端发布。

最终汇报按以下格式：

```text
结论：本机可交付候选 / 尚未达到候选

已完成阶段：G00—Gxx
通过验证：...
构建产物：绝对路径、大小、SHA256
现有阻塞：...
未完成验收：...
Git状态：...
是否推送/部署/发布：否（除非另有明确授权）
```

---

## 12. 参考架构的使用边界

本次方案借鉴 `cc-haha` 的职责分层、专用Agent、Skill来源治理、分类记忆、追加式任务日志、预算、取消、并发和恢复思想，但不得直接照搬：

- 不迁移到Electron/TypeScript。
- 不将平台绑定到Claude专用协议。
- 不允许模型生成并执行JavaScript/Python工作流代码。
- 不用Git worktree代替业务文件版本、模板锁或成果身份。
- 不把开发者Agent的宽权限原样用于财务和评估业务场景。

本项目继续采用 Python、PySide6、现有Office/WPS适配器、FastAPI服务端和现有发布链；新架构必须通过兼容层渐进迁移。

---

## 13. 执行开始条件

读取完本文件后，立即执行 G00：

1. 进入权威工作树。
2. 核对分支、HEAD和dirty状态。
3. 创建执行账本。
4. 运行基线测试。
5. 建立或更新`CONTEXT.md`与首批ADR。
6. 验证G00后自动进入G01。

不要先询问“是否开始”，不要先重构UI，不要先做多Agent界面，不要先发布远端版本。先建立正确的输入边界、自然语言理解和上下文契约。
