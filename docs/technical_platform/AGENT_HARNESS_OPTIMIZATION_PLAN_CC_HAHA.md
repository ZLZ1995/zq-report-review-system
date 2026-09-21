# ZQ 技术平台 Agent 与 Harness 优化方案

> 研究对象：`https://github.com/NanmiCoder/cc-haha`  
> 制定日期：2026-09-18  
> 当前范围：方案设计，不修改业务代码、不推送 GitHub、不部署 Zeabur。  
> 适用基线：`D:\ZQ-Acceptance\local-feature-checkout`，分支 `codex/local-platform-feature-update`。

## 1. 结论摘要

`cc-haha` 对本项目最有价值的不是 Electron、React 或 Claude 专用实现，而是以下工程思想：

1. UI、宿主、会话服务、模型执行进程严格分层，调用只经过受控协议。
2. 用户输入先形成稳定的消息与附件快照，再经过 Hook、上下文装配和工具/Skill 发现。
3. Skill 不是一段提示词，而是带来源、优先级、适用条件、工具权限、模型、执行上下文和生命周期 Hook 的能力包。
4. 记忆分类型、分作用域、带索引、按需检索、带陈旧警告，并与当前事实复核。
5. 长任务和多 Agent 任务有统一状态、预算、取消、进度、输出文件和恢复日志。
6. Workflow 对并发、Agent 数量、Token、同步脚本时间、输出大小和恢复确定性都有硬上限。
7. 专门的 Explore、Plan、Verification 等 Agent 使用不同工具池，而不是让一个全能 Agent 承担所有职责。

本项目已有任务身份、文件哈希、Skill 版本、权限收据、DAG、事件存储、取消、任务恢复和记忆的基础，但目前仍是“多个局部安全模块围绕单任务串联”。下一阶段应把它升级成统一的：

```text
输入网关
  → 本轮上下文快照
  → 结构化意图理解
  → 能力检索与路由
  → 声明式计划编译
  → 权限与预算决策
  → 可恢复 Workflow Harness
  → 白名单 Skill/工具执行
  → 独立验证
  → 对话流式交付
  → 记忆候选与 Skill 反馈
```

## 2. 对 cc-haha 的有效提取

### 2.1 值得借鉴

#### A. 进程与职责边界

`cc-haha` 将 Electron 主进程、React UI、本地 sidecar、每会话 CLI 子进程和外部适配器分开。UI 不直接执行模型或本地工具，所有原生能力通过明确桥接协议。

对本项目的启发：

- PySide UI 只提交命令和显示事件。
- Agent Runtime 不直接操作 Qt 控件。
- Harness 只调度具备契约的 Tool Adapter。
- Office/WPS、浏览器、文件生成、远程模型分别使用独立 Worker/Adapter。
- 云端模型服务不接触本地路径和原始二进制文件。

#### B. Skill 多来源与优先级

`cc-haha` 区分 bundled、managed、user、project、plugin、MCP 等来源，同时支持适用路径、工具范围、模型覆盖、inline/fork 执行方式和 Hook。

对本项目的启发：Skill Registry 应从“内置/外部”二分法升级为有优先级和治理状态的多来源注册表，并兼容 `.agents/skills/` 开放目录，但企业锁定模板仍必须由 managed/builtin 层覆盖，不能被用户同名 Skill 替换。

#### C. 记忆分型和按需召回

`cc-haha` 将长期记忆分为 user、feedback、project、reference；索引始终加载，正文最多选择少量相关记录，并提示记忆可能过期。它明确规定能从代码/当前状态推导出的事实不应进入记忆。

对本项目的启发：不能继续把所有“历史对话”和“项目偏好”压成同一段文本。应把偏好、用户确认、项目事实、外部引用和 Skill 经验分层，并始终保留来源、版本、有效期和撤销状态。

#### D. 后台记忆抽取

`cc-haha` 在主回复结束、没有待处理工具时，由受限子 Agent 提取记忆；子 Agent 只能写记忆目录，不能修改项目；主 Agent 已写记忆时跳过，避免重复。

对本项目的启发：可增加“记忆候选提取器”，但由于本项目涉及财务与客户资料，不应直接自动写入正式记忆。应先生成候选，只有明确的用户偏好/纠正可自动标记为待确认，其余项目事实必须经用户确认。

#### E. Workflow Harness

`cc-haha` 的 Workflow 具有：并发限制、Agent 上限、Token 预算、阶段事件、单 Agent 跳过/取消、结构化输出、工作树隔离、追加日志、结果缓存和确定性恢复。

对本项目的启发：当前 `harness.py` 的串行 DAG 要升级为资源感知、预算感知、可恢复、可并行的通用 Harness，并把进度直接映射到对话。

#### F. 任务通知与流式状态

`cc-haha` 把任务状态、输出增量、完成通知和任务面板统一建模，断开 UI 不自动终止任务，重连后以服务端/运行时状态为准同步。

对本项目的启发：审核、生成、浏览器和更新不应各自拼装状态文案，应统一使用 Task Event Protocol；“60%卡住”应被阶段、批次、当前工具、等待原因和可取消状态替代。

#### G. 权限是策略矩阵，不只是模式名称

`cc-haha` 的权限模式最终仍映射到每类工具、路径、命令和风险判断。模式只提供默认决策，具体动作仍有规则解释和拒绝历史。

对本项目的启发：已实现的三档模式应继续保留，但必须落到统一 `PermissionDecision`，并显示动作、对象、风险、决策依据和租约有效期。

### 2.2 不应照搬

1. 不迁移到 Electron/TypeScript。当前 PySide6、Python Office/WPS COM 和既有测试资产更符合项目实际。
2. 不允许模型生成任意 Python/JavaScript 编排脚本并直接执行。`cc-haha` 使用 VM、禁用 import/随机数/当前时间并隔离跨 Realm 对象，但本项目仍应采用更窄的声明式 DAG。
3. 不采用“所有 Agent 默认可编辑”的策略。业务原件只读、模板锁定和隐藏表隔离必须是不可覆盖的强约束。
4. 不让客户端配置供应商 API Key。模型、渠道和计费继续由云端总控控制。
5. 不把完整对话、文档正文或模型输出写入遥测和记忆。
6. 不为了多 Agent 而多 Agent。简单审核/生成任务保持单执行 Agent；只有可独立并行且能独立验证的任务才拆分。

## 3. 当前项目差距

| 领域 | 当前状态 | 主要缺口 |
|---|---|---|
| 输入 | 已绑定当前轮选择的附件，支持分支上下文 | 缺统一 Turn Envelope；文字、附件、引用、权限模式、模型和项目状态分散在多个调用参数中 |
| 自然语言理解 | `AgentController` + 服务端 TaskUnderstanding + 本地校验 | 缺意图层级、否定/时间/对象约束、交付物、风险和不确定性明细；澄清粒度仍偏粗 |
| 上下文 | 最近 6 条用户消息 + 确认记忆字符预算 | 字符预算不是 Token 预算；没有来源清单、摘要层、冲突检测、文档片段预算和可观察 Context Manifest |
| Skill | 真实 Registry、版本、规则哈希、模板锁、外部 ZIP 安装 | 契约缺 negative triggers、示例/反例、网络/资源预算、可组合输出语义、迁移兼容和 Skill 评估集 |
| Planner | 模型方案编译为受信任 `ExecutionPlan` | 主要围绕固定业务步骤；缺通用条件分支、并行组、重试/回退/补偿和预算 |
| Harness | 串行 DAG、权限复核、事件边界、unknown 对账 | 缺并行调度、节点租约、恢复日志、缓存键、阶段进度、资源配额、单节点重试与独立验证节点 |
| Agent | 主 Agent 负责理解与编排 | 缺稳定的角色 Agent 契约与工具池；验证经常与执行同源，独立性不足 |
| 记忆 | user/project/session、确认、撤销、版本、预算 | 缺 feedback/reference/skill-learning 分层、待确认抽取、相关性选择、陈旧警告、冲突与合并 |
| 进度 | 有任务事件、批次和取消 | 多业务模块事件格式不完全统一；用户仍难知道“正在做什么、为何等待、能否重试” |
| 可观测性 | 执行账本和部分事件 | 缺统一模型调用 Trace、上下文清单、路由解释、节点耗时、重试原因和脱敏诊断包 |

## 4. 目标 Agent 架构

### 4.1 Agent 不再是一个类，而是六层职责

```text
Conversation Agent（用户协作与最终表达）
  ├─ Intent Analyst（只读：理解目标、对象、约束、交付物）
  ├─ Capability Router（只读：检索 Skill/工具候选）
  ├─ Plan Compiler（只读：生成声明式计划并由本地规则编译）
  ├─ Domain Executor（按 Skill 白名单执行）
  ├─ Independent Verifier（只读或临时目录：验证结果）
  └─ Memory Curator（只生成记忆候选，不获得业务文件写权限）
```

浏览器任务增加专门的 `Browser Operator`，但仍由 Harness 提供页面租约、账号租约和动作权限。

### 4.2 每类 Agent 的默认工具池

| Agent | 默认权限 | 允许工具 | 禁止事项 |
|---|---|---|---|
| Intent Analyst | 只读 | 当前消息、附件元数据、能力摘要、确认记忆 | 文件写入、浏览器写操作、模型外再派生任务 |
| Capability Router | 只读 | Skill Registry 查询、依赖/状态检查 | 直接执行 Skill、修改注册表 |
| Plan Compiler | 只读 | 契约读取、类型检查、DAG 编译 | 任意脚本、业务文件读写 |
| Domain Executor | 契约限定 | Skill 声明工具、当前轮目标文件、任务目录 | 访问历史未选文件、覆盖原件、越过输出目录 |
| Independent Verifier | 只读+临时证据 | 结果文件读取、哈希、渲染、结构/公式/版式校验 | 修改交付件；复用执行 Agent 的未经验证结论 |
| Memory Curator | 仅记忆候选 | 消息摘要、已确认结果、记忆候选表 | 读取密码/API Key、写正式记忆、读取未授权业务正文 |
| Browser Operator | 页面租约限定 | 观察、导航、滚动、受控点击/填入/上传/下载 | 获得明文密码、跨 origin、把网页文字当授权 |

### 4.3 启用多 Agent 的条件

满足任一条件才拆分：

- 两个以上互不依赖的文件组可并行处理。
- 生成后必须有独立版式/公式验证。
- 需要先研究资料类型，再分别生成两个以上成果。
- 浏览器操作与本地文件生成可形成明确的先后阶段。
- 单 Agent 上下文预计超过预算。

禁止拆分：

- 单文件、单 Skill、可在一次确定性流程完成的任务。
- 多 Agent 会同时写同一 Word/Excel/输出目录。
- 需要共享 Office COM 实例或同一浏览器页面写租约。

## 5. Turn Context：解决自然语言和旧附件串入问题

新增不可变 `TurnEnvelope`，成为理解、计划、执行和恢复的唯一输入：

```text
schema_version
owner / project_id / session_id / turn_id / message_id
raw_user_text
normalized_text
explicit_references[]
selected_attachment_versions[]
newly_attached_ids[]
historical_reference_ids[]
active_model_id
permission_mode
browser_tab/page_version（如适用）
locale / timezone / submitted_at
prior_clarification_chain[]
```

规则：

1. 本轮没有选中的历史附件不能进入 `selected_attachment_versions`。
2. “审核刚上传的两个文件”“只看报告，不看明细表”等限定先由确定性解析器固化，再交给模型理解。
3. 理解、规划和执行都校验同一个 TurnEnvelope 哈希。
4. 任何附件、会话、模型或权限变化都使旧理解结果失效。
5. UI 提交后可展示“本轮资料范围”摘要，让用户及时发现错选。

建议新增：

- `turn_context.py`
- `turn_normalizer.py`
- `turn_scope_policy.py`
- `tests/technical_platform/test_turn_context.py`

## 6. 自然语言理解优化

### 6.1 四阶段理解

#### 阶段 1：确定性预解析

不调用模型，提取：

- 明确文件名、数量、扩展名和“本次/之前/刚上传”等时间指示。
- 动作：审核、生成、修改、批注、上传、下载、登录、安装 Skill、查询。
- 否定与排除：不要、不含、只、除非、仅参考、隐藏表不参与。
- 交付形式：Word、Excel、PDF、对话回复、批注副本、上传回执。
- 明确授权或撤销：允许、不要询问、停止、取消权限。

该阶段只形成事实候选，不决定最终 Skill。

#### 阶段 2：模型结构化理解

要求模型返回严格 schema：

```text
intent
goal
targets[]
references[]
excluded_inputs[]
deliverables[]
constraints[]
assumptions[]
required_capabilities[]
risk_flags[]
ambiguities[]
next_action = ask | plan | answer
```

模型不得直接给工具名作为最终授权，只能提出能力需求。

#### 阶段 3：本地一致性裁决

- 目标必须来自 TurnEnvelope。
- PDF 只能参考的业务规则优先于模型。
- 修改/批注必须区分原件和副本。
- 生成类任务检查模板和来源资料是否满足最小条件；缺科目余额表时不得机械阻断，应由资料分类器判断现有资料能支持到什么程度。
- 自然语言理解与文件实际类型冲突时进入澄清。

#### 阶段 4：最小澄清

只询问会改变计划或交付结果的问题。问题带 2–3 个互斥选项，并展示各选项影响。能从资料或项目设置可靠推断的内容不反问。

### 6.2 理解评估集

建立至少 120 条中文真实表达的离线评估集，覆盖：

- 省略主语、口语、错别字、连续多要求。
- “只审核这两个新文件”等附件范围。
- 否定、双重否定、条件句和例外。
- 一句话要求多 Skill 串联。
- 用户纠正前一轮理解。
- “生成评估明细表”但资料不齐全。
- 浏览器/OA 操作与本地生成组合。
- 安装 ZIP Skill 与普通 ZIP 资料的区分。
- 只问问题、不授权执行。

验收：目标/参考/排除文件准确率 100%；高风险动作漏澄清 0；不必要澄清率低于 10%；错误 Skill 执行率 0。

## 7. 上下文管理优化

### 7.1 Context Manifest

每次模型调用前构建并保存脱敏清单：

```text
system_policy_hash
turn_envelope_hash
skill_summaries[id, version, rules_hash]
selected_memory_ids[version, freshness]
conversation_summary_id
evidence_chunk_ids[file_id, version, visibility]
tool_receipt_ids
token_budget_by_section
```

用户可在诊断界面看到“用了哪些来源”，但看不到系统提示词全文、价格、Token 明细或密钥。

### 7.2 分层预算

建议顺序和默认预算比例：

1. 系统安全与业务红线：固定、不可裁剪。
2. 本轮 TurnEnvelope：固定、不可裁剪。
3. 当前 Skill 契约：固定、只加载选中 Skill 全文。
4. 文件证据：50%–65%，按目标优先于参考。
5. 相关记忆：最多 5 条，5%–10%。
6. 最近会话摘要：10%–15%，不重复原始附件正文。
7. 工具回执：按引用加载，旧大输出落盘。

从“字符数裁剪”升级为模型 Token 估算；每段保留来源、哈希和截断原因。

### 7.3 压缩原则

- 压缩的是对话历史和工具输出，不压缩本轮限制、文件身份、金额、日期、公式和证据引用。
- 文档正文用结构化片段和证据 ID，不反复传整篇。
- 审核后的问题清单存为结构化事实，下一轮只加载未解决/需复核问题及必要证据。
- 任何摘要都标记“非原始证据”；最终判断必须回查原片段。

建议新增：

- `context_manifest.py`
- `context_budget.py`
- `conversation_compactor.py`
- `evidence_retriever.py`

## 8. 记忆架构优化

### 8.1 三个存储平面

#### A. 协作记忆

- `user`：用户角色、表达偏好、长期使用习惯。
- `feedback`：用户明确纠正或确认的工作方式，必须记录 Why 和 How to apply。
- `project`：无法从当前文件推导的项目背景、截止日期和范围决定。
- `reference`：OA 项目、外部系统入口等指针，不保存密码。

#### B. 运行记忆

- 当前会话摘要、未完成任务、澄清链、任务回执。
- 有明确生命周期，任务完成后归档，不进入长期个性化记忆。

#### C. Skill 学习

- 误判/漏判案例、用户验收标签、适用范围、失败原因、修正规则建议。
- 与正式 Skill 版本分离；达到样本阈值并通过回归后才能形成新版本。

### 8.2 记忆记录字段

```text
id / scope / type / key / text
source_message_ids[] / source_task_ids[]
created_at / valid_from / valid_until
status = proposed | confirmed | revoked | superseded
version / supersedes
sensitivity
confidence
verification_policy
last_verified_at
```

### 8.3 记忆候选流程

1. 主回复结束、无活动工具后异步抽取候选。
2. 只处理新消息增量，不重新扫描整个历史。
3. 检测主 Agent 是否已创建同类候选，避免重复。
4. 用户纠正/明确偏好可显示“建议记住”；项目事实和业务结论必须由用户确认。
5. 正式写入前执行去重、冲突和敏感信息检查。
6. 召回时最多 5 条，带陈旧提示；若与当前文件冲突，以当前证据为准并建议撤销旧记忆。

### 8.4 安全约束

- 不记录 API Key、密码、Cookie、完整客户文档、身份证号、银行账号或未脱敏金额明细。
- 不把模型推断自动存成事实。
- 不把能从代码、当前模板、Git 或任务结果查到的信息复制进长期记忆。
- 提供“本轮忽略记忆”“查看来源”“撤销”“忘记全部项目记忆”。

## 9. Skill 系统优化

### 9.1 Skill Contract v2

每个 Skill 除 `SKILL.md` 外应生成可机读契约：

```text
id / name / version / source / trust_level
description / when_to_use / when_not_to_use
positive_examples[] / negative_examples[]
input_roles[] / required_inputs[] / optional_inputs[]
supported_extensions[]
output_types[]
allowed_tools[]
network_policy
modifies_originals = false
template_locks[]
resource_locks[]
model_policy / token_budget
acceptance_gates[]
feedback_schema
compatibility / migration
```

### 9.2 来源优先级

```text
managed/builtin 锁定业务 Skill
  > 平台官方签名 Skill 更新
  > 项目级 Skill
  > 用户安装外部 Skill
  > 远程/MCP 临时能力
```

同 ID 冲突时不静默覆盖。锁定模板 Skill 只允许官方签名版本接管。

### 9.3 常用基础 Skill 清单

建议新增或正式化以下工程 Skill：

1. `material-classifier`：判断资料类型、期间、主体和可支持任务，不机械要求科目余额表/序时账。
2. `turn-scope-resolver`：根据自然语言和当前轮附件确认目标/参考/排除资料。
3. `office-runtime-preflight`：检测 Office/WPS、COM、文件锁、输出目录和字体。
4. `document-evidence-indexer`：生成带来源和版本的 Word/PDF/Excel 可见证据索引。
5. `spreadsheet-formula-auditor`：检查公式、链接、金额单位、隐藏表和汇总口径，但不改模板。
6. `document-layout-verifier`：渲染 Word/PDF 并检查页数、溢出、字体、表格和批注。
7. `artifact-integrity-verifier`：验证原件哈希不变、成果可打开、模板锁和交付清单。
8. `task-reconciliation`：处理 unknown、网络响应丢失、服务端已执行但客户端未收到的任务。
9. `provider-diagnostics`：模型渠道、usage 字段、超时、限流和备用渠道诊断。
10. `browser-receipt-verifier`：登录/上传/下载后的独立页面和文件回执校验。
11. `memory-curator`：生成、合并、陈旧检查和撤销记忆候选。
12. `skill-lint-and-eval`：校验 Skill 契约、模板锁、正反例和最小验收集。

这些基础 Skill 是 Agent/Harness 的支撑能力，不应在普通用户界面要求手动切换。

## 10. Harness 目标设计

### 10.1 使用声明式 Workflow，不执行模型生成代码

```text
WorkflowPlan
  identity
  turn_envelope_hash
  plan_revision
  budget
  phases[]
  nodes[]
  edges[]
  output_contract
  acceptance_gates[]
```

节点类型限定为：

- `understand`
- `classify_materials`
- `extract_evidence`
- `model_call`
- `run_skill`
- `browser_action`
- `validate_artifact`
- `verify_business_result`
- `ask_user`
- `deliver`

模型只能提出节点和依赖；本地编译器负责把节点映射到可信 Adapter，并拒绝未知类型。

### 10.2 调度能力

- DAG 就绪队列和并行组。
- 资源锁：Office/WPS、同一输出目录、同一工作簿、浏览器页面、模型并发。
- 预算：模型调用次数、Token 预估、整轮余额冻结、文件数、运行时间。
- 每节点超时、有限重试、指数退避和不可重试分类。
- 取消树：取消父任务会停止未开始节点、通知运行节点，并等待资源安全释放。
- 节点状态：queued/running/waiting_user/waiting_resource/succeeded/failed/cancelled/unknown/reconciliation_required。
- 独立 verifier 节点不复用 executor 的自然语言结论。

### 10.3 Workflow Journal

采用追加式记录：

```text
run_created
node_claimed
node_progress
node_result_committed
node_failed
permission_granted/revoked
resource_acquired/released
artifact_registered
run_terminal
```

每个完成节点使用缓存键：

```text
plan_revision + node_id + adapter_version + input_hashes
+ skill_version + rules_hash + permission_snapshot + dependency_result_hashes
```

恢复规则：

- 已完成且缓存键一致的节点可重放结果。
- 首个不一致/未完成节点起重新执行后续依赖链。
- 服务端模型任务优先按 `client_job_id` 对账，不直接重发扣费调用。
- Office/浏览器写动作状态不明时进入 reconciliation，不自动重放。

### 10.4 进度协议

统一事件：

```text
phase_started / phase_completed
node_queued / node_started / node_progress
node_waiting_resource / node_waiting_user
node_retrying / node_succeeded / node_failed
artifact_ready / task_completed
```

UI 应显示：当前阶段、当前节点、已完成/总数、等待原因、最近活动时间、是否可停止；百分比只作辅助，不再使用无法解释的假进度。

## 11. 权限架构优化

保留现有三档：请求批准、帮我批准、完全访问权限。新增统一决策对象：

```text
PermissionDecision
  mode
  action
  resource
  scope
  risk_level
  policy_rule
  decision = allow | ask | deny
  reason
  lease_id / expires_at / single_use
```

硬性 deny 不受完全访问权限覆盖：

- 修改原始业务文件。
- 上传隐藏/veryHidden 工作表内容。
- 客户端读取供应商 API Key。
- 未选中的历史附件进入任务。
- 外部 Skill 执行未登记脚本。
- 跨项目/跨账号/跨浏览器 origin 使用旧授权。
- 在系统盘默认创建业务资料和成果。

## 12. 可观测性与诊断

新增本地脱敏 Trace：

- task/turn/plan/node/attempt ID。
- 模型、渠道、请求开始结束、首 Token 延迟、状态、重试原因。
- Context Manifest 的 ID 和预算，不记录正文。
- Skill、规则和模板哈希。
- 工具、资源等待、Office/WPS 选择、浏览器 origin。
- 服务端 job ID、计费 hold/capture/refund 状态；客户端 UI 不显示 Token 与金额。
- 产物 ID、SHA256、验证状态和交付路径摘要。

提供“一键导出诊断包”：默认排除文档正文、密码、Cookie、API Key、完整路径中的客户名称；用户可预览后导出。

## 13. 分阶段施工清单

### P0 工程基线与 ADR

目标：冻结真实边界，避免边改边猜。

修改：

- 建立/更新仓库 `CONTEXT.md`。
- 新增 ADR：Agent 分层、TurnEnvelope、记忆治理、声明式 Workflow、权限硬约束、Context Manifest。
- 建立结构化离线理解评估集。

验收：首次进入仓库的 Agent 可在 5 分钟内定位主链路；ADR 与 Skill 规则无冲突；现有完整回归保持通过。

### P1 TurnEnvelope 与输入网关

目标：彻底解决旧附件混入、本轮范围漂移和迟到理解结果。

修改：统一消息、附件、引用、权限、模型和澄清链快照；所有后续阶段只接收 envelope ID/hash。

验收：新附件/旧附件、重命名、删除、替换、取消、会话切换、迟到结果、分支引用等至少 40 项边界测试通过；误带旧文件为 0。

### P2 自然语言理解 v2

目标：先理解用户真正要做什么，再选 Skill。

修改：确定性预解析、结构化 schema、本地裁决、最小澄清、路由解释。

验收：120 条中文评估集；目标/参考/排除准确率 100%，错误执行 0，不必要澄清率低于 10%。

### P3 Context Manifest 与 Token 预算

目标：让每次模型调用的上下文来源可解释、可复现、可控。

修改：分层预算、证据检索、会话摘要、工具大输出落盘、冲突和截断记录。

验收：同一输入生成稳定 manifest；本轮红线不被裁剪；隐藏表片段永不出现；长会话 Token 使用显著下降且审核召回率不下降。

### P4 记忆 v2

目标：记忆有用但不污染业务事实。

修改：三平面、四类协作记忆、候选提取、确认、相关性检索、陈旧提示、合并/撤销、敏感信息扫描。

验收：用户纠正可形成候选；未经确认的项目事实不影响任务；撤销后不再召回；过期/冲突记忆提示并以当前证据为准；敏感样本写入率 0。

### P5 Skill Contract v2 与基础 Skill

目标：Skill 可检索、可组合、可验证、可安全更新。

修改：扩展契约、来源优先级、`.agents/skills` 兼容、正反例、Skill lint/eval、基础能力补齐。

验收：同名冲突不静默覆盖；锁定模板只能由官方签名版本更新；每个正式 Skill 有正反例与最小验收集；自然语言路由命中率达到目标。

### P6 Workflow Harness v2

目标：支持多阶段、并行、预算、取消、恢复和对账。

修改：声明式 DAG、资源调度、追加日志、缓存键、重试策略、reconciliation、统一事件。

验收：进程中断后恢复不重复扣费；同一 Office/输出目录无并发写；取消无僵尸 Worker；unknown 不自动重放；所有节点状态可解释。

### P7 专门 Agent 与独立验证

目标：执行和验证职责分离。

修改：定义 Agent Profile、工具池、模型策略、并行触发条件、独立 verifier。

验收：简单任务不额外拆 Agent；复杂任务可并行；验证 Agent 无成果修改权限；故意制造的公式/版式/哈希错误均能被拦截。

### P8 对话流式交付与任务面板

目标：像 Codex 一样在对话中持续反馈真实进度和成果。

修改：统一事件渲染、阶段卡片、等待原因、停止/重试、节点详情、成果链接；不恢复“成果”独立栏。

验收：解析、模型、Office、验证、上传等阶段都能看到真实状态；不再长期卡在无解释的 60%；重启后恢复同一任务状态。

### P9 真实场景与发布验收

目标：本机、GitHub、Zeabur、更新链共同可用。

验收矩阵：

- 报告审核两轮及批注副本。
- 评估明细表模板、公式、链接和万元单位。
- 工商历史沿革字体和缩进。
- 财务简报及 Office/WPS。
- 外部 Skill ZIP 安装与平台 Skill 更新。
- OA 登录、验证码接管、合成文件上传、回执核验。
- 断网、余额不足、渠道切换、响应丢失、重复请求。
- 干净 Windows 全新安装、历史升级、失败回退。

只有全部门禁有证据后，才进入 GitHub Release 和总控 stable。

## 14. 建议优先级

最先做：P0 → P1 → P2 → P3。它们直接解决“Agent 不理解用户、夹带旧文件、上下文浪费和路由不稳定”。

第二批：P4 → P5。它们解决个性化、Skill 扩展和长期可维护性。

第三批：P6 → P7 → P8。它们提升复杂任务、多 Agent、恢复能力和用户可见进度。

最后：P9 联合发布验收。

不要先实现多 Agent UI，再补 TurnEnvelope 和 Harness；否则只是把当前范围和状态问题复制到更多 Agent。

## 15. 总体验收指标

| 指标 | 目标 |
|---|---:|
| 未选历史附件被带入任务 | 0 |
| 隐藏表内容进入模型上下文 | 0 |
| 原始文件被修改 | 0 |
| 同一请求重复扣费 | 0 |
| 高风险意图未澄清即执行 | 0 |
| 自然语言错误 Skill 执行 | 0 |
| 用户取消后继续产生外部副作用 | 0 |
| 记忆敏感信息写入 | 0 |
| 简单任务无必要多 Agent | 0 |
| 任务阶段/等待原因可解释率 | 100% |
| 成果具备来源、版本、哈希和验证状态 | 100% |

## 16. 建议新增文件

```text
src/asset_based_agent/technical_platform/
  input_gateway.py
  turn_context.py
  turn_normalizer.py
  intent_schema.py
  intent_policy.py
  context_manifest.py
  context_budget.py
  conversation_compactor.py
  evidence_retriever.py
  agent_profiles.py
  workflow_plan.py
  workflow_compiler.py
  workflow_runtime.py
  workflow_journal.py
  workflow_scheduler.py
  workflow_events.py
  workflow_reconciliation.py
  memory_candidates.py
  memory_selector.py
  memory_consolidation.py
  diagnostic_bundle.py

tests/technical_platform/
  fixtures/intent_eval_zh.jsonl
  test_turn_context.py
  test_intent_understanding_v2.py
  test_context_manifest.py
  test_context_budget.py
  test_memory_candidates.py
  test_memory_retrieval_v2.py
  test_skill_contract_v2.py
  test_workflow_runtime.py
  test_workflow_resume.py
  test_workflow_resources.py
  test_agent_profiles.py
```

现有 `harness.py`、`agent_controller.py`、`context.py` 和 `memory_service.py` 不应一次性重写。先用兼容适配层引入新契约，待新旧路径回归等价后，再逐步迁移并删除旧入口。

## 17. 研究依据

- `cc-haha` Desktop Architecture：进程边界、sidecar、WebSocket 重连和持久化边界。
- `cc-haha` Skills Usage/Internals：多来源 Skill、工具权限、条件激活、fork 上下文与 Hook。
- `cc-haha` Memory Usage/Internals：四类记忆、索引、相关性选择、陈旧警告、后台抽取和受限工具。
- `cc-haha` Multi-Agent Usage：Explore/Plan/Verification 等角色、后台任务、隔离和并行。
- `cc-haha` Workflow 源码：Harness 限额、Token 预算、VM 隔离、结构化输出、Journal 和确定性恢复。
- 本项目：`GOAL_INTEGRATED_DELIVERY_CHECKLIST.md`、`LOCAL_FEATURE_UPDATE_CHECKLIST.md`、`KIMI_CODE_HANDOFF.md` 及当前技术平台源码。

该方案吸收结构思想，不复制与本项目业务、安全和技术栈不匹配的实现。
