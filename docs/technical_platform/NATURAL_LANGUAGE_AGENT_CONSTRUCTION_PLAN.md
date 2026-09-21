# ZQ 技术平台：自然语言 Agent / Harness 文件施工清单

状态：待实施计划；本文件创建不代表各阶段已经完成。
编制日期：2026-09-15。
2026-09-16 补充：在线更新、通用内置浏览器、网站凭据管理、Agent 浏览器操作和多分支并发已整合到 INTEGRATED_AGENT_PLATFORM_PLAN_V2.md；OA 仅为网站集成案例，不与浏览器绑定。本清单作为基础细项保留，后续实施顺序以 V2 阶段映射为准，不将历史状态自动标为完成。
工程根目录：D:/1/1/ai-excel-agent。

## 1. 目标与产品边界

产品定位：以项目为核心的专业工作助手。用户表达目标，Agent 理解、澄清和规划，Skill 提供专业方法，Harness 校验权限、执行与成果。不得把“已选中 Skill”当作“已充分理解任务”。

执行前必须明确：目标、对象和版本、目标/参考/排除资料、操作边界、必要输入、预期成果、验收条件。证据不足时追问，不依赖模型自报的高置信度放行。

保持不变的红线：

- 原件默认只读；批注、生成是独立副本操作，必须绑定本轮授权。未来修改原件能力不在本次默认开放范围。
- 隐藏及 veryHidden 工作表不作为审核、定位、检索、记忆或上传来源；不追查隐藏依赖。生成副本时仅允许原样保留封装数据。
- 原始文件不上传；只允许受控的可见文本片段进入模型。业务资料、缓存、日志中的业务内容和成果不得默认写 C 盘。
- 锁定 Word/Excel 模板不变，Excel 预设链接、公式及单位口径不因架构改造调整。
- 客户端不配置或保存供应商 API Key；模型调用必须经服务端鉴权、余额及计费门禁，用户只看余额。
- 项目浏览、资料管理、已有结果查看等本地行为可离线；需要模型判断时联网，不静默用关键词执行器替代语义理解。
- 用户忽略问题不等于确认误判；一次纠正不自动改通用 Skill；外部包安装不等于代码执行许可。

## 2. 编号、路径与验收规则

本次独立编号 NL00—NL07，不覆盖旧 Txx 或旧“第一/二/三阶段”的历史状态。

文件表路径前缀均相对于上述工程根目录：

| 前缀 | 目录 |
|---|---|
| TP | src/asset_based_agent/technical_platform |
| SRV | src/asset_based_agent/report_review_server |
| RA | src/asset_based_agent/report_review_app |
| TTP | tests/technical_platform |
| TSRV | tests/report_review_server |
| TRA | tests/report_review_app |
| DOC | docs/technical_platform |
| DEP | deploy/report_review_server |

“改”表示复用现有文件；“增”表示拟新增文件，尚未落地。“条件增/改”有明确触发条件，不能当作已完成。所有新增 Python 包目录同时补 __init__.py（数据/测试用例目录除外）。

每阶段执行：确认输入基线 → 补失败用例 → 实现最小闭环 → 专项测试 → 邻近回归 → 记录证据 → 阶段签收。未通过不进入依赖阶段。测试次数不与通过用例数混算；模拟模型、真实模型、原生 Office/WPS、EXE 和线上部署分别记录。

最终状态至少区分：未开始、施工中、自动化通过、实机待验收、验收通过、发布完成。不得只用一个“完成”覆盖全部状态。

## 3. 阶段总表

| 阶段 | 目标 | 依赖 | 退出门槛 |
|---|---|---|---|
| NL00 | 冻结基线与安全回归 | 无 | 当前源码/测试/包/线上版本分别可追溯；回退资料齐全 |
| NL01 | 从分类路由升级为任务理解 | NL00 | 咨询、执行、否定、追问及未支持请求分流正确 |
| NL02 | 会话续接与文件范围解析 | NL01 | 多轮指代、回答追问、范围变更不串任务或文件 |
| NL03 | Skill 与工具契约统一 | NL02 | 已启用能力可发现、可校验；无执行器不假装可执行 |
| NL04 | 计划式 Harness 与恢复取消 | NL03 | 多步骤、授权、重试、幂等与状态转换受控 |
| NL05 | 对话接续、成果与批注闭环 | NL04 | 问题解释/忽略/批注/导出能够绑定正确任务执行 |
| NL06 | 分层记忆与 Skill 改进治理 | NL05 | 记忆可解释、可撤销，更新可评测和回滚 |
| NL07 | 语义、实机、打包和部署验收 | NL00—NL06 | 发布矩阵、真实验证和回滚演练通过 |

## 4. NL00：基线冻结与工程验收基础

### 目标

保留近期已实现的文件范围、取消、自动路由、批注及快捷键；区分源码能力与旧 EXE/服务器能力。不整体推倒现有业务执行器。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 00-01 | 增 | DOC/NL_BASELINE.md | 记录 Git 状态、当前源码、EXE、ZIP、服务器构建/协议、模板及 Skill 哈希；未验证处写未知 |
| 00-02 | 增 | DOC/NL_ACCEPTANCE_LOG.md | 分阶段记录命令、退出码、用例数、失败、复测、风险和签收，不覆盖失败证据 |
| 00-03 | 改 | scripts/check_technical_platform.py | 纳入新增测试目录，支持明确的测试产物目录和报告输出 |
| 00-04 | 改 | scripts/test_report_review_productization.py | 纳入平台回归，继续按进程隔离 Qt/旧客户端/服务端测试，保留超时和异常码 |
| 00-05 | 增 | scripts/check_agent_release_baseline.py | 只读核对发布文件、规则及模板哈希、测试范围和待验收项；不打印密钥 |
| 00-06 | 复用/补测 | TTP/test_file_drop.py、test_task_cancellation.py、test_composer_keys.py、test_annotation_followup.py、test_project_catalog.py | 锁定近期修复和只读/存储范围 |
| 00-07 | 复用 | DOC/RELEASE_0_2_6.md、AGENT_HARNESS_OPTIMIZATION.md | 仅作为历史证据，不把旧进度直接改标成新阶段完成 |

### 修改方案与验收

1. 只读检查脏工作区，建立本次允许变更文件清单；不撤销既有修改。
2. 对数据库、配置和原件使用测试副本；不得拿正式项目迁移试错。
3. 跑三套当前回归，记录已知 Qt/Windows 文件占用故障，稳定复现后另立修复项；不能用多次重跑掩盖问题。
4. 测试产物写 D 盘项目 outputs/nl_acceptance/<run-id>/，不得包含真实密钥、客户文件或未脱敏日志。

验收：原始模板和业务原件哈希不变；全量基线和例外清单明确。回退：本阶段不改变业务协议和数据结构。

## 5. NL01：任务理解层

### 目标

把 RoutePlan 的单个 skill_id 改为可校验的“理解结果”。先判断是否需要执行，不要求每条消息都上传文件或调用业务 Skill。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 01-01 | 增 | TP/agent_contracts.py | 定义 MessageIntent、TaskUnderstanding、EvidenceRef、MissingInput、UnderstandingDecision 等版本化对象 |
| 01-02 | 增 | TP/agent_controller.py | 统一接收消息、启动理解、展示追问/理解摘要、转交执行；不放 Qt 控件及供应商调用实现 |
| 01-03 | 增 | TP/understanding_policy.py | 校验目标/对象/约束/缺项，判定可执行、需追问、仅回答或拒绝；不能仅用置信度阈值 |
| 01-04 | 改 | TP/routing.py | 变为可取消的理解客户端适配；保存请求 ID，记录失败与取消，不把错误变成默认审核 |
| 01-05 | 改 | TP/app.py | 去掉“所有消息必须选文件”的前置拦截；文件要求下移到任务门禁；对话转交 controller |
| 01-06 | 改 | RA/services/remote_auth_service.py | 新增理解接口封装，复用单 API 前缀、鉴权刷新、错误脱敏 |
| 01-07 | 增 | SRV/services/task_understanding.py | 受控目录+上下文形成模型请求，返回结构化理解；请求大小、输出字段、费用估算有界 |
| 01-08 | 增 | SRV/prompts/task_understanding.txt | 意图、否定、假设、仅讨论、多目标及不支持能力规则；输出简短依据而非思维链 |
| 01-09 | 改 | SRV/schemas.py、api.py | 增加版本化理解协议，建议 POST /api/v1/agent/understand；明确与执行分离 |
| 01-10 | 改 | SRV/services/skill_routing.py | 旧 /skill-route 保持兼容适配；不得在旧客户端缺少授权信息时开放新写入能力 |
| 01-11 | 改/增 | TTP/test_automatic_routing.py；增 test_task_understanding.py；TSRV/test_skill_routing.py；增 test_task_understanding.py | 模型模拟、JSON 缺失/越界、未知 ID、鉴权、取消和旧协议测试 |

### 修改方案

理解结果至少包含目标、message_intent、目标/参考/排除对象、限制、交付要求、缺项、依据消息 ID、候选能力和下一步动作。候选 Skill 不是最终执行授权。

普通说明可直接回答；有专业作业意图才进入 Skill 发现。模型不可用时允许本地管理，解释暂不能理解/执行，不静默猜任务。自然语言中自带文件路径、报价、授权字样不自动成为可信系统字段。

### 验收

- 无附件输入“软件能做什么”可获得说明，不提示必须上传文件。
- “先别审核，解释流程”“不要生成明细表，只核对报告”不误执行。
- 不支持的写原件请求解释边界，不偷偷改成只读预检。
- 模型返回不存在的能力、字段矛盾或空缺依据时不创建业务任务。
- 取消理解后不进入执行；模型调用的费用边界明确，不承诺请求取消等于零消耗。

回退：受能力开关控制；旧路由仅供旧版兼容，不作为新协议失败时的静默执行降级。

## 6. NL02：会话状态、资料理解与范围解析

### 目标

理解“这份、刚上传的、第二条、按刚才说的做”；通过明确状态完成追问，不重放全部历史对话或所有项目文件。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 02-01 | 增 | TP/conversation_state.py | 持久化当前任务、待答问题、已确认字段、任务修订号及取消状态 |
| 02-02 | 增 | TP/reference_resolver.py | 将文件别名、版本、问题序号、成果引用解析为真实 ID；歧义返回候选，不猜 |
| 02-03 | 增 | TP/file_scope.py | 管理本轮目标/参考/排除集合，核对 UI、自然语言与最终快照一致性 |
| 02-04 | 改 | TP/context.py | 在理解前构建相关上下文；加入 Agent 的未决询问及受控成果摘要，排除无关旧指令 |
| 02-05 | 改 | TP/material_analysis.py | 必要时只读识别资料类型；按需使用安全片段，不把通用意图理解与整文件解析绑死 |
| 02-06 | 改 | TP/store.py、project_catalog.py | 新状态按 owner/project/session 隔离；迁移和读取错误不自动创建替代工作区 |
| 02-07 | 增 | TP/local_migrations.py；TP/migrations/001_conversation_state.sql | 引入本地 schema 版本、迁移事务和兼容检查；采用新增表而非覆盖旧记录 |
| 02-08 | 改 | TP/app.py、task_spec.py | 上传批次有 ID；同名版本更新可解释；冻结选定文件和理解版本 |
| 02-09 | 复用/补测 | RA/services/document_extraction_service.py、privacy_filter.py | 继续使用现有可见性门禁；不得为指代解析单独绕开过滤读取隐藏内容 |
| 02-10 | 增 | TTP/test_conversation_state.py、test_reference_resolver.py、test_file_scope.py、test_local_migrations.py | 多轮、跨会话、版本、迁移和歧义测试 |
| 02-11 | 改 | TTP/test_context.py、test_file_drop.py、test_store.py、test_project_catalog.py | 防止旧行为回归 |

### 修改方案

“可以”绑定 question_id + task_revision，而非自由文本全局授权。新消息若修改范围，递增修订号，失效旧计划；历史引用只能检索授权项目内的特定对象。仅文件名相似不足以选定版本。资料足够的简单项目允许缺科目余额表/序时账，不恢复一刀切必填。

上下文只加载足够完成当前判断的消息、成果索引和可见证据。附件内容与网页/包内文字均是数据，不能覆盖用户指令。需要打开未选历史资料时，先明确告知范围变化，存在歧义或敏感扩大时追问。

### 验收

- 两个同名报告必须能区分版本，未确定时不启动审核。
- 旧流水不因新上传报告而重新参与；允许用户明确指定历史流水作为本轮参考。
- 回复一次追问可以接续原任务；旧问题的“是”不能授权新任务。
- “第二条”能定位到特定审核结果；有多个候选时问清楚。
- 数据迁移在旧项目副本执行两次仍一致，故障可恢复；跨账号读取为零。

回退：迁移前备份项目数据库至该项目选定的非系统盘位置；旧客户端不得打开不兼容的新库，不自动执行破坏性降级。

## 7. NL03：Skill 与工具能力契约

### 目标

专业规则、执行能力和权限明确分离。内置/外部 Skill 同一套发现及验证流程；不通过随意执行包内脚本来实现“智能”。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 03-01 | 增 | TP/skill_contracts.py | 输入角色、可选替代资料、输出、验收、后续动作、依赖、模板指纹和工具要求 |
| 03-02 | 增 | TP/capability_registry.py、skill_discovery.py | 生成可执行能力目录，先检索候选再读取完整规则；检查版本和适配器就绪状态 |
| 03-03 | 增 | TP/tool_contracts.py | 工具声明读写副作用、网络、幂等、取消方式、输出类型及校验器 |
| 03-04 | 改 | TP/skills.py、skill_package.py、skill_installation.py、skill_manager.py | 支持新契约、旧包兼容和启用检查；安装/启用/可执行状态分开 |
| 03-05 | 增 | TP/builtin_contracts/report_review.json、detail_workbook.json、company_history.json、preflight.json | 声明当前四种能力；从真实执行器能力出发，不虚构全格式支持 |
| 03-06 | 改 | .codex/skills/valuation-report-review-edit/skill.manifest.yaml；valuation-detail-workbook-fill/skill.manifest.yaml；gongshang-change-history-docx/skill.manifest.yaml | 补齐契约或明确映射到平台 sidecar；兼容原有 CLI 使用，避免重复规则漂移 |
| 03-07 | 改 | TP/review_rules.txt、TP/task_spec.py、SRV/services/task_understanding.py | 规则版本、平台只读审核能力和原技能编辑能力明确区分；客户端/服务端协议一致 |
| 03-08 | 增 | TTP/test_skill_contracts.py、test_capability_registry.py、test_tool_contracts.py | 输入输出、可选资料、未知工具、冲突能力、版本固定测试 |
| 03-09 | 改 | TTP/test_skill_package.py、test_skill_installation.py、test_skill_manager_ui.py、test_review_skill_sync.py、test_detail_skill_update.py | 外部包与模板指纹兼容回归 |

### 修改方案与验收

审核 Skill 的“完成后询问批注”进入 post_actions 契约，执行器不再靠模型输出一句话触发。完整技能规则按需加载，不能只截取前 1000 字视为完整理解。外部声明超出受支持工具范围时标记不可执行，并说明缺什么适配器。

验收：内置和已启用外部能力可被检索；停用/版本切换在任务中不能偷换规则；缺少可选资料的简单项目仍能规划；模板哈希和原 CLI 回归不变。旧包兼容只保留已有能力，不自动增加写入授权。

回退：保留旧包及锁文件，按契约版本选择适配；禁用新能力不会删除已有项目数据。

## 8. NL04：计划式 Harness、授权及运行控制

### 目标

支持多步骤任务和中途变更，确保每一步都按本轮版本、权限、成本和验收条件执行。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 04-01 | 增 | TP/planner.py、execution_plan.py | Plan/Step、依赖、输入输出引用、估计成本类别、验收和失败策略 |
| 04-02 | 增 | TP/harness.py、task_state.py | 通用调度、合法状态转换、领取/租约、检查点、终止及结果归档 |
| 04-03 | 增 | TP/permissions.py | 授权绑定用户、任务修订、文件哈希、动作、问题 ID、目录；范围变化即失效 |
| 04-04 | 增 | TP/task_recovery.py、event_store.py | 持久事件和断线/崩溃恢复；已执行的步骤不重新盲跑 |
| 04-05 | 增 | TP/tool_dispatcher.py；TP/adapters/review.py、generation.py、annotation.py、report_export.py | 包装现有执行器，统一参数、取消、产物与失败协议 |
| 04-06 | 改 | TP/execution.py、task_spec.py、store.py | TaskSpec v2 与 v1 兼容读取；旧快照用于显示而非恢复授权；入口逐步转到 Harness |
| 04-07 | 增 | TP/migrations/002_plans_events_approvals.sql | 本地计划、步骤、事件、授权及恢复信息新增表 |
| 04-08 | 改 | TP/generation.py、generation_worker.py、annotations.py、excel_annotations.py、report_export.py | 统一工具结果和原件/模板校验；可取消边界必须真实，不强杀 Office 进程 |
| 04-09 | 改 | RA/services/remote_review_llm.py、remote_auth_service.py、task_cancellation.py | 幂等标识、远端状态查询、取消确认、迟到结果处理和重连 |
| 04-10 | 改 | SRV/services/review_job_service.py、metered_model_service.py、wallet_service.py | 将计划步骤与原计费/hold对应；使用量及结算以服务端为准，避免重复扣款 |
| 04-11 | 改 | SRV/api.py、schemas.py、models.py | 定义状态/事件/取消查询协议；仅保存必要云端执行元数据 |
| 04-12 | 条件增 | DEP/migrations/versions/<next_revision>_agent_step_state.py | 若新增云端状态列/表则使用实际 Alembic head 生成修订号，禁止猜编号；无表变更则记录无需迁移 |
| 04-13 | 增 | TTP/test_planner.py、test_harness.py、test_permissions.py、test_task_recovery.py、test_event_store.py | 步骤依赖、变更、取消、授权复用、恢复和幂等 |
| 04-14 | 改 | TTP/test_execution.py、test_task_claim.py、test_task_spec.py、test_task_cancellation.py；TSRV/test_review_jobs.py、test_metered_model_service.py、test_billing_api.py、test_migrations.py | 旧任务、计费、数据库和取消链路回归 |

### 修改方案

先实现顺序计划，后按实际需要开放独立步骤并行；本阶段不引入多 Agent 或任意代码执行沙箱。每步具有稳定 step_id 与幂等键；重试同一逻辑调用复用，用户改变范围形成新修订并重新授权。

本地项目数据库记录对话和业务文件；服务端是认证、钱包、调用计量及远端任务状态的权威，不能信任客户端声称“未执行所以免扣费”。必要业务临时上下文沿用加密和最长 24 小时清理，不把整个本地会话复制到云端。

取消必须区分：已发出请求、服务端已确认、当前供应商调用尚在结束、本地已停止后续步骤。远端状态不明时显示待核对，不能当作已取消或失败后重新扣费执行。

### 验收

- “先识别资料，再填表，再核对输出”严格按依赖执行；验证失败不发布正式成果。
- 上传新版本/更换目录/增加写操作后，旧授权不能复用。
- 模拟执行中断网、超时、进程退出、重复点击、事件乱序和迟到回调，不重复执行或结算。
- 取消各阶段均在约定边界内停止后续动作；不能虚假宣称供应商请求瞬时终止。
- 当前业务原件和锁定模板保持不变。

回退：先停止新计划入口，保留状态查询及结算；待活动任务核对后再回退版本，不删除云端账本或强行降级数据库。

## 9. NL05：对话操作、问题与成果闭环

### 目标

“解释第三条、忽略第二条、生成批注、导出记录、用新版本复核”均可自然接续，但关键写入仍有明确授权。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 05-01 | 增 | TP/followup_controller.py、review_actions.py | 绑定 task_id/issue_id/version，处理解释、忽略、复核、批注和导出 |
| 05-02 | 增 | TP/artifact_registry.py、output_validation.py | 统一成果来源、文件哈希、验证状态、位置数量、问题数量和失败原因 |
| 05-03 | 增 | TP/ui/conversation_presenter.py、approval_panel.py、task_progress.py、artifact_links.py | 对话渲染、必要授权、真实阶段/事件进度、文件及目录入口 |
| 05-04 | 改 | TP/app.py、composer.py | app 保留窗口装配，业务逻辑逐步移出；保留 Enter/Alt+Enter、拖拽与滚动行为 |
| 05-05 | 改 | TP/annotations.py、excel_annotations.py、report_export.py、diagnostics.py | 统一接入工具/成果协议；逐文件成功和失败单独登记；不得用保存成功替代业务真实性 |
| 05-06 | 增 | TP/migrations/003_review_actions_artifacts.sql | 问题操作、成果及每轮后续询问状态持久化 |
| 05-07 | 条件增/改 | SRV/services/review_conversation.py；SRV/api.py、schemas.py | 仅在现有模型接口无法支持按问题解释时新增受控对话接口，走相同鉴权/计费/范围门禁 |
| 05-08 | 增 | TTP/test_followup_controller.py、test_review_actions.py、test_artifact_registry.py、test_output_validation.py、test_task_progress.py | 自然语言接续、错轮次、防伪成果、事件恢复测试 |
| 05-09 | 改 | TTP/test_annotation_followup.py、test_export.py、test_composer_keys.py、test_file_drop.py、test_window.py、test_diagnostics.py | 保真、拒绝/取消、不重复询问、历史入口、快捷键回归 |
| 05-10 | 条件增 | TSRV/test_review_conversation.py | 若新增问题对话接口，验证账号、问题范围、幂等和费用 |

### 验收

- “第二条”不跨任务解释或忽略；无法定位先问。
- 完整审核且有问题时询问一次批注；拒绝不重复；再次主动请求可进入授权。
- 不因允许批注就应用正文修改建议；对话最终修改方案不自动进入标准审核报告。
- 所有交付入口只能指向已验证且归属当前用户的成果；文件删除/移动能正确提示。
- Word 正文、表格、既有批注、Excel 可见/隐藏页、公式、链接、宏分别设计样本；不支持的锚点如实跳过。
- 流式进度展示已发生的事件与内容，不用假百分比制造进展；断线恢复不重复追加消息。

回退：成果注册表保留可读；新 UI 可关闭，但不能绕开写入授权或重新恢复手动 Skill 必选。

## 10. NL06：分层记忆与 Skill 改进治理

### 目标

形成可追溯的任务记忆、项目事实、用户偏好和优化候选；不得让模型自动修改规则、模板或历史事实。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 06-01 | 增 | TP/memory_contracts.py、memory_service.py、memory_retrieval.py | 来源、适用范围、有效期、状态、版本及撤销；按当前任务检索 |
| 06-02 | 增 | TP/feedback_service.py、skill_improvement.py | 区分忽略/误判/偏好；创建改进提案、附证据和关联测试，不自动发布 |
| 06-03 | 改 | TP/context.py、store.py、skill_installation.py | 撤回即时生效；账号/项目隔离；规则切换只影响授权的新任务 |
| 06-04 | 增 | TP/migrations/004_memory_proposals.sql；TP/ui/memory_panel.py | 记忆历史、提案与用户可见的来源/删除入口 |
| 06-05 | 增 | SRV/services/skill_release_service.py | 通用 Skill 的审批、版本发布、兼容声明和回滚；不接收未授权的客户原文 |
| 06-06 | 改 | SRV/models.py、schemas.py、api.py；SRV/admin_assets/index.html、app.js、style.css | 管理员审批和版本记录；客户端不得自授管理员权限 |
| 06-07 | 条件增 | DEP/migrations/versions/<next_revision>_skill_release_registry.py | 审批/发布需要的新增表，按当时真实 head 创建 |
| 06-08 | 增 | TTP/test_memory_service.py、test_memory_retrieval.py、test_skill_improvement.py；TSRV/test_skill_release_service.py | 记忆冲突、过期、撤回、越权审批、版本回滚 |
| 06-09 | 改 | TTP/test_context.py、test_store.py、test_skill_installation.py；TSRV/test_admin_web.py | 原用户和管理行为回归 |

### 验收

- “以后本项目金额按万元显示”只能影响允许的展示偏好，不改锁定模板的公式、金额事实或预设口径。
- 一次忽略不成为误判规则；未核实模型判断不能变成项目确定事实。
- 删除记忆后，后续理解与执行不再注入；已发生任务保留当时快照用于追溯，不伪造历史。
- 公共 Skill 提案必须经过测试、管理员批准和版本发布，失败可回滚。
- 禁止跨客户传播原文证据；共享改进只使用获准、脱敏或合成案例。

回退：关闭新记忆召回/优化发布，保留审计记录，不删除项目数据或自动退回旧业务口径。

## 11. NL07：语义、实机及配套发布

### 目标

证明不是“代码有接口”，而是自然语言任务能端到端正确完成，并能在客户机器运行和安全回退。

### 文件施工清单

| ID | 操作 | 文件 | 施工内容 |
|---|---|---|---|
| 07-01 | 增 | tests/agent_acceptance/cases/intent.jsonl、dialogue.jsonl、scope.jsonl、permissions.jsonl、recovery.jsonl | 至少100条基础语义用例；独立留出改写/多轮集，不把全部用例用于调提示词 |
| 07-02 | 增 | tests/agent_acceptance/scoring.py、test_replay.py；scripts/evaluate_agent_semantics.py | 计算意图、对象、排除项、追问和授权正确性，不只判断 Skill ID |
| 07-03 | 增 | scripts/run_agent_e2e.py | 从输入消息到理解、确认、执行、验证、成果的本地端到端测试 |
| 07-04 | 改 | TP/release_info.py；SRV/api.py、config.py | 客户端/服务端构建号、协议及能力版本；缺接口时阻止相关任务而非重复报笼统网络错误 |
| 07-05 | 改 | scripts/build_technical_platform.py、package_technical_platform.py、export_client_release.py | 打包新增模块、迁移、能力契约及资源；校验允许清单，排除日志/数据库/客户附件/密钥 |
| 07-06 | 改 | scripts/smoke_technical_platform_exe.py | 登录、输入法/快捷键、拖拽、对话路由、取消及成果入口的 EXE 冒烟 |
| 07-07 | 改 | DEP/Dockerfile、requirements.txt、start.py、README.md、ZEABUR.md | 仅按实际新增依赖和启动迁移需求修改；明确密钥、持久卷、清理任务及兼容升级顺序 |
| 07-08 | 改 | TTP/test_release_info.py、test_build_dependencies.py；TSRV/test_openapi_contract.py、test_migrations.py | 新旧协议矩阵、打包资源、迁移及缺能力提示 |
| 07-09 | 增 | DOC/NL_SEMANTIC_ACCEPTANCE.md、NL_WINDOWS_ACCEPTANCE.md、NL_DEPLOYMENT_ROLLBACK.md、NL_RELEASE_MANIFEST.json | 用例标签/评分、实机矩阵、发布回退和最终源码/EXE/ZIP/服务端哈希证据 |
| 07-10 | 改 | DOC/RELEASE_READINESS_CHECKLIST.md、README.md | 入口、用户操作、能力边界、已验证及待验证状态更新 |

### 验收方案

1. 单元/集成：平台、旧审核客户端、服务端在独立进程全量通过；新增模块静态检查通过。
2. 自然语言：明确单一任务的端到端理解正确率初始目标 ≥95%；分别报告各类别及端到端完成率，不以总平均掩盖某类失败。
3. 硬门禁：测试集中，未授权写入、历史文件误带、跨账号读取、隐藏内容上传、重复执行结算均为零；出现一次即不放行。
4. 真实模型：对留出用例重复测试稳定性；人工复核理解、选定文件和结果依据。仅在确认测试账号、非敏感材料、渠道和费用上限后运行，不用现有客户任务反复试错。
5. 实机：Windows 干净环境，分别测试 Office、WPS、二者并存和均未安装。无组件时按能力正确阻止相关计算/生成，不影响纯本地浏览。
6. 文档：在 Office/WPS 打开交付副本，检查文字、锚点、已有批注、公式、链接、宏和隐藏状态；ZIP/哈希通过不能代替视觉或意见真实性验收。
7. 输入：中文输入法候选确认不误发送，Enter发送、Alt+Enter换行、长按不重复，拖拽和忙碌禁用正常。
8. 故障：真实/模拟断网、超时、关闭窗口、服务重启、数据库迁移中断、包版本错配；状态和费用可核对。
9. 发布：先兼容服务端及必要迁移，验证健康和能力接口，再发布新客户端；版本开关和回滚演练通过。旧客户端不兼容时提供升级提示，不能自动授予新权限。
10. 最终交付：EXE目录、ZIP、哈希清单、安装/操作说明、验收报告、发布及回滚记录全部对应同一版本。

## 12. 统一接口与数据约定

- 理解对象 Understanding：理解版本、消息意图、目标、证据引用、对象候选、限制、缺项、可执行判定；不包含可自行生效的写授权。
- 任务对象 TaskSpec v2：owner/project/session/task/revision、精确文件版本、理解快照、计划、Skill/工具版本、授权引用和验收门禁。
- 执行对象 Step：稳定 ID、依赖、输入/输出、状态、幂等键、取消语义和验证结果。
- 问题对象 Issue：稳定 ID、来源及位置证据、性质、用户操作、审核轮次；展示序号不是数据库身份。
- 成果对象 Artifact：来源任务/步骤、类型、文件位置和哈希、验证状态、创建时间；只给已验证成果正式入口。
- 授权对象 Approval：明确动作、目标集合及版本、目录、任务修订、批准来源及时间；过期/撤销/变更均失效。
- 事件对象 Event：单调序号、任务及步骤身份、事件类型、可公开的摘要和时间；重放可去重，不保存密钥和隐藏片段。

所有 JSON 协议均需 schema_version、字段校验、大小上限、未知字段处理策略及兼容用例。数据库升级只由迁移器执行，不由模型生成 SQL 后直接运行。

## 13. 依赖、联调与保留文件

必须复用：认证/钱包/模型网关、可见性过滤器、项目本地存储、锁定模板、原有 Word/Excel 业务执行器。未发现必要性前不新增向量数据库、消息队列、多 Agent 框架或任意代码执行环境。

不改内容：assets/builtin_templates/ 下的正式模板及预设链接；正式业务输入文件；已发布旧包；用户凭据与钱包账本。若现有技能规则或模板元数据与新的平台契约冲突，建立单独问题记录，不擅自改模板解决。

客户端数据库迁移与云端 Alembic 迁移分开验证。业务文本长期保存仍以用户选择的本地项目目录为准；云端只保存必要的认证、计量、执行元数据及获准的限时加密上下文。所有真实发布/充值/账号变更须遵循当次授权范围。

## 14. 每阶段签收模板

- 阶段/施工项 ID：
- 本次新增/修改文件及哈希/提交：
- 实现了哪些用户可见行为：
- 未实现/不支持/待确认项：
- 失败用例与修复前证据：
- 验证命令、环境、用例数、退出码、报告位置：
- 模拟模型 / 真实模型 / Office / WPS / EXE / 线上：分别标记：
- 只读、模板、隐藏表、账号、计费、取消回归结果：
- 迁移与回滚证据：
- 是否满足本阶段退出门槛：
- 下一阶段是否允许开始：

## 15. 首批施工范围

先实施 NL00 和 NL01。NL00 完成基线确认后，NL01 第一小轮仅增加理解契约与失败测试，第二小轮接服务端理解接口，第三小轮接客户端咨询/追问/执行分流，第四小轮做权限与旧协议回归。不要同一轮同时重写 UI、计费、Skill 和数据库。

本清单列的是施工目标，不是当前功能完成情况。计划编制期间未执行业务代码修改、数据库迁移、付费模型调用、EXE 构建或云端部署。
