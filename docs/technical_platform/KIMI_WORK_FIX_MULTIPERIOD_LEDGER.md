# 多期间同类资料路由修复 执行账本（F00—F07）

任务书：`docs/technical_platform/KIMI_WORK_FIX_MULTIPERIOD_MATERIAL_ROUTING.md`
执行日期：2026-09-19

## F00 基线与现场保护

- 实际执行仓库：`D:\ZQ-Acceptance\local-feature-checkout`（origin = ZLZ1995/zq-report-review-system）。
  - 偏离任务书字面路径 `D:/1/1/ai-excel-agent` 的理由（已核实，非臆断）：
    该仓库 master HEAD `cbc7d94`，`src/asset_based_agent/technical_platform/` 整目录未跟踪（`??`），
    其 `material_analysis.py` 为旧快照（无本轮已验收的 6 项修复：节选 1500/3 次重试/原因透出等），
    且工作树有 863 个用户未提交改动。本轮修复必须叠加在已验收代码之上，故在
    local-feature-checkout 的 `codex/local-platform-feature-update` 分支执行。
- 分支：`codex/local-platform-feature-update`；HEAD：`5bf8444`（Raise server material-analysis reply budget to 8192 tokens）。
- 工作树状态：仅任务书副本 `docs/technical_platform/KIMI_WORK_FIX_MULTIPERIOD_MATERIAL_ROUTING.md` 未跟踪，无其他脏文件。
- Python：`D:\1\1\ai-excel-agent\.venv\Scripts\python.exe`（3.10），pytest 需 `PYTHONPATH=src --basetemp=D:/ZQ-Acceptance/tmp-pytest-basetemp -p no:cacheprovider`。
- AGENTS.md（主仓库 HEAD 版）要点：中文场景禁 PowerShell（本账本全程 Git Bash）；保留用户未提交改动；docx 结构保护（本轮不涉及）。
- 技能 `valuation-detail-workbook-fill/SKILL.md`（452 行）已通读。关键事实：
  管道 `run_detail_workbook_pipeline.py` 已支持 `--financial-statement` 重复参数与
  `select_latest_statement`（同主体多期选最新，封面元数据取自原始表头）——Skill 侧已就绪。
- 缺陷定位（真实调用链）：
  - `technical_platform/material_analysis.py::resolve_roles` 单值角色映射，第二份非 other 同类
    资料抛 `ValueError('存在多份同类资料，需要先确认本轮使用的主体和期间')` —— 线上故障原文一致。
  - 消费方：`generation.py::_execute_generation`（L246 `roles, plan = provider.analyze(...)`），
    仅在 analyze 返回后才写 `material_analysis.json`（消歧失败时无落盘，符合任务书 2.2.5）。
  - `generation_worker.py::detail` 目前只传 `--financial-statement bs`（单期）。
  - 状态机：`store.transition` 现无 `waiting_user`；`workflow_events.py`/`task_panel.py` 已有
    `node_waiting_user` → `waiting_user` 的事件词汇映射可接入。
- 真实故障证据（线上复现，本日 17:06）：run `b08511b9…`，events 末尾
  `execution: ValueError`，对话文案"失败原因：存在多份同类资料，需要先确认本轮使用的主体和期间"。
  证据库：`D:\ZQ-Acceptance\real-machine-test\20260919-dialogfix\data10\platform.sqlite`。
- 既有测试 `tests/technical_platform/test_material_analysis.py`：含重复角色即 ValueError 的旧语义断言，
  F01/F02 将按新契约改写。
- 未修改任何业务代码。

## F01 复现并固定失败测试

- 新增 `tests/technical_platform/test_material_multiperiod.py`，夹具 `make_statement` 用 openpyxl
  生成带"编制单位/报表日期"表头的合成资产负债表。
- 修复前验证：同主体三期解析测试稳定抛出线上原文 ValueError（7 红 1 绿），失败原因与线上截图一致，
  非夹具错误。修复后该复现测试改写为 `test_fixed_same_entity_multiperiod_no_longer_raises_duplicate`
  钉住新行为。
- 覆盖任务书 F01 五项：同主体三期选最新、不同主体等待澄清、同主体同期间冲突等待澄清、
  单期兼容回归、模型成功但消歧待确认时原始分析工件已落盘。
- 命令：`pytest -q tests/technical_platform/test_material_multiperiod.py` → 17 passed。

## F02 资料分析与消歧契约

- `material_analysis.py` 重写：新增 `MaterialCandidate`/`MaterialResolution` dataclass（与任务书第 4 节
  契约语义等价）、`statement_metadata`（只读 openpyxl 扫前 6 行表头取编制单位+日期，正文证据、
  不用文件名/mtime）、`resolve_materials`（同主体多期→resolved 选最新+comparison；
  不同主体/同期间冲突/期间不可识别/非报表角色重复→waiting_user 带具体问题）、
  `resolve_roles` 兼容包装（旧调用方语义不变）、`resolution_snapshot`（可序列化审计）、
  `apply_resolution_override`（澄清恢复，override 严格 ⊆ 已识别候选，零模型调用）。
- 缺 `name`/`path` 的旧式 files 条目容错（`by_id[...].get('name', id)`）。
- `apply_resolution_override` 的 comparison 仅含同主体且不同期间的候选；被否掉的异主体报表或
  同期间被替代版本不作对比资料（防止异主体数据流入管道）。
- 旧测试 3 处断言按新契约改写为 `resolution.selected`；`test_analysis_rejects_unknown_file_and_ambiguous_role`
  保持 ValueError 语义（经 resolve_roles 包装）。
- 命令：`pytest -q tests/technical_platform/test_material_multiperiod.py tests/technical_platform/test_material_analysis.py` → 15 passed（后增至 21 passed）。

## F03 worker 与 Skill 输入

- `generation.py::_execute_generation`：resolved 时 comparison 文件复制为 `financial_statement_<i>.<ext>`，
  `selected['financial_statements'] = [最新主表] + comparison`（仅多期时写入，单期任务 inputs 不变）。
- `generation_worker.py::detail`：消费 `inputs['financial_statements']`，展开为重复
  `--financial-statement` 参数（最新在前）；无该键时保持旧单参行为（兼容旧 job）。
- 管道侧无需改动：`run_detail_workbook_pipeline.py --financial-statement action="append"` 与
  `select_latest_statement` 原生支持多期，封面/基准日按正文期间取最新。
- 测试：`test_detail_skill_update.py` 新增 2 项（多期转发最新在前、无列表时旧单参兼容）→ 6 passed。
- F03 验收（合成多期到本地生成入口、原件哈希不变）并入 F06 真实文件复测一并验证通过。

## F04 Harness 状态机与恢复

- `waiting_user` 全链路接线：
  - `store.py::transition`：running/validating→waiting_user，waiting_user→running/cancelled/failed。
  - `tool_dispatcher.py` ToolOutcome.status Literal 增加 'waiting_user'。
  - `adapters/generation.py`：waiting_user 结果落 StepResults 并以 waiting_user ToolOutcome 返回；
    禁止携带业务 artifacts。
  - `harness.py::_execute_claimed_plan`：waiting_user outcome → save_result + transition + return。
  - `execution.py`：waiting_user 状态返回已存结果。
  - `compound_task.py`：waiting_user 时返回 `{'kind': 'waiting_user'}` 不再 RuntimeError。
- **schema v12 迁移**（`local_migrations.py::apply_v12`）：重建 `execution_steps` 表放宽 CHECK 约束
  纳入 'waiting_user'。沿用既有版本化迁移机制：写入前自动备份到 `migration-backups/`，
  合成/古老库缺表时跳过；回滚方式 = 恢复自动备份。`store.py` 新建库序列接入 apply_v12。
  新增 `test_v11_upgrade_rebuilds_step_state_check_and_preserves_rows`（旧约束拒绝 waiting_user、
  迁移后行保留且接受 waiting_user）。`test_release_info.py` 身份断言更新为 0.2.10/schema 12
  （客户端版本不动，schema 随下次发版一起走）。
- 恢复机制（重启可恢复、不重复计费）：
  - `generation.py`：override 恢复路径读已落盘 `material_analysis.json`/`material_resolution.json`，
    经 `apply_resolution_override` 重建 resolution，不调模型；恢复时复用自有工作目录
    （`generation_work_directory(create=False)` + 目录缺失报错），首次运行仍防目录碰撞。
  - `event_store.py::claim`：允许从 'waiting_user' 步骤重新认领（checkpoint/结果已持久化）。
  - `step_results.py::save`：仅当既有结果为 waiting_user 占位时允许被恢复后的最终结果取代，
    其余 immutability 不变。
  - `permissions.py::_binding`：binding 排除 `material_resolution_override`（仅能收窄到已识别候选，
    不扩大授权范围；与 execution_context 同例）。
  - `store.py::set_material_resolution_override`：仅 waiting_user 状态可写入澄清快照并留事件。
  - `interrupt_active_runs` 只碰 queued/running/validating，waiting_user 重启后保留。
- `material_resume.py::match_clarification`：纯函数，按主体名/期间措辞/文件名保守匹配
  pending 候选；每个多候选角色须恰好唯一命中，否则返回 None 继续追问；零模型调用。
- `app.py::try_resume_waiting_run`（submit 钩子）：本会话最新 waiting_user run 优先消费回复——
  含"取消/放弃"→cancelled；匹配失败→带原问题追问；匹配成功→写 override、经
  register_task_worker/TaskWorker 恢复执行（provider 绑定快照模型与规则指纹，实际不会被调用）。
  `continue_local_chain`：waiting_user 时停放链式任务不清空不推进，恢复成功后再续。
- 计费幂等测试 `test_resume_after_clarification_skips_model_and_completes`：
  首轮 waiting_user（模型 1 次）→ 澄清恢复（假 worker）→ succeeded，模型调用仍为 1 次。

## F05 对话与可观察性

- 成功路径：progress 逐条输出识别结果与选择理由（"同一主体（X）识别到 N 期…选择最新一期 …"）。
- 等待路径：result.feedback 含识别结果 + 具体澄清问题；`completed()` 状态栏
  "等待补充信息，请在对话中回复主体、期间或文件名"；`conversation_stream.TERMINAL_TEXT` 与
  `task_panel` 终态标签增加 waiting_user 映射（修复 `.get` 回退把等待误标为"任务完成"的隐患，
  及 task_panel 直接键查会 KeyError 的隐患）。
- 测试：`test_ui_hook_ignores_sessions_without_waiting_run`、
  `test_ui_hook_reasks_when_clarification_stays_ambiguous`、
  `test_ui_hook_cancels_waiting_run_on_user_request` 覆盖无等待/追问/取消三类对话路径。

## F06 回归与真实文件复测

- 完整回归（技术平台 179 个测试文件分三批显式清单，排除开工前既有收集错误文件
  `tests/test_detail_review_release.py`——缺 `test_detail_workbook_pipeline_guards` 模块，与基线一致）：
  - 批 1：328 passed（169.85s）；批 2：450 passed（146.68s）；批 3：446 passed（87.10s）。
  - `tests/test_detail_scope_first.py`：10 passed。
  - 合计 1234 passed，0 failed，无新增失败。
- 真实文件复测（`D:\ZQ-Acceptance\real-machine-test\20260919-dialogfix\real\`，北京绵脉三期报表+
  余额表+流水，只读）：
  - 确定性消歧（零模型）：三期报表正文识别 2024-12-31/2025-12-31/2026-06-30，
    resolved 选 2026-06-30 主表，2024/2025 保留为 comparison，reasons 可审计。
  - 端到端（data12，假 provider 返回与真实成功运行一致的角色映射——流水=bank_statement、
    余额表=other，真 worker 子进程全管道）：run succeeded，detail_workbook.xlsx 生成且
    验收通过；job inputs 含 financial_statements 三期列表（最新在前）；封面
    "被评估单位：北京绵脉科技有限公司 / 评估基准日：2026 年 6 月 30 日"正确；
    模型调用 1 次；五个原件哈希前后一致。
  - 反面对照（data11）：若把余额为空的余额表强行作 bank_statement，管道业务门禁
    `bank_statement_balance_mismatch` 准确拦截（禁止替代取数）——证明失败路径报错精确、
    不被本次修复稀释。

## F07 复查与交付

- diff 复查：20 个改动文件全部属于本轮范围（状态机接线/消歧契约/worker 输入/恢复钩子/文案/测试），
  542 insertions / 39 deletions；无 UI 发布、云端部署等无关内容混入。
- 敏感扫描：全量 diff 无账号、密码、API Key、Cookie、Token、真实银行账号、绝对业务资料路径；
  测试夹具中真实主体名已脱敏为合成名称（22 处替换后 17/17 仍绿）。
- 异常包装检查：waiting_user 与业务门禁失败均透出真实原因，未包装成"网络/模型服务连接"。
- 重试扣费检查：恢复路径零模型调用（测试钉住 calls==1）。
- 兼容性：旧单值 `balance_sheet` 消费方不变；`resolve_roles` 旧语义保留；schema v12 迁移自动备份。
- 远端动作：本轮未推送 GitHub、未建 Release、未部署 Zeabur、未激活在线更新。

## 候选包实机验收追加轮（2026-09-19 晚）

### 新发现并修复的缺陷（提交 33d55d2）

- 现象：真实五文件场景在计划确认后状态栏报"计划或授权校验未通过，未启动业务步骤"，runs 表为空。
- 根因（traceback 证据）：`execute_compound` → `build_compound_task_spec` → `_fields` 抛
  `ValueError: Generator reference roles are not supported by its input contract`——
  理解层把"银行-绵脉(1).xlsx"标为参考角色后，app.py 路由条件（references 非空即走组合计划）
  与编译层契约（生成器步骤禁止 reference_inputs）互相矛盾，凡"单生成器+参考文件"任务必失败。
- 修复：DETAIL（自动资料识别生成器）放行 reference_inputs；适配器把参考文件标注
  `user_role='reference'` 传入资料识别；发往模型的摘录前加"仅作参考资料，不作为填报依据"提示
  （纯客户端改动）。HISTORY 等定位角色生成器保持严格契约。
- 测试：新增 `tests/technical_platform/test_compound_detail_references.py` 4 个用例
  （编译放行/HISTORY 仍拒绝/适配器标注/提示前缀），全量回归 1662 passed / 1 skipped / 0 failed
  （tests/technical_platform + report_review_app + report_review_server，QT_QPA_PLATFORM=offscreen）。

### 源码实机验证（修复后、真实模型、data13）

- run d07a6e951d3f4614b684f71b189c66b3：state=succeeded，验收门
  source_evidence / output_validation / original_hash_unchanged 全过。
- 资料识别覆盖全部 5 个文件；参考文件（银行-绵脉(1).xlsx）参与识别但未作填报依据。
- 多期间路由：balance_sheet 取 2026-06-30 期（19376B），2024/2025 两期作 comparison，
  流水作 bank_statement。
- 产物 detail_workbook.xlsx（528,957 B）封面：被评估单位=北京绵脉科技有限公司，
  评估基准日=2026年6月30日（F9/H9/J9 单元格）。
- 五个原件 SHA256 前后一致（只读未改）。

### 过程中确认的非代码问题

- 服务端 model_unavailable（409）系误报：重放脚本把 display_name（deepseek-flash）当 model_id；
  用 UUID model_id 重放 200（1.8s）。管理台核对模型与渠道均 enabled、api_key_configured=true。
- "任务理解未完成"多次出现为到 Zeabur 的间歇性 TCP 连接超时（httpx ConnectTimeout，
  能力预检阶段），同一时刻 urllib/httpx 直连验证通过——网络抖动，非服务端或客户端缺陷。

### 候选包

- 第一候选（20260919-1945，提交 2572b3b）：冒烟 PASS（client=0.2.10; schema=12）、
  冻结扫描 0 命中，但实机验收暴露上述参考角色缺陷，作废。
- 第二候选（20260919-2235，提交 33d55d2）：构建中，待冒烟+实机验收。
- 远端动作：仍未推送 GitHub、未建 Release、未部署 Zeabur、未激活在线更新。

### 第二候选包（20260919-2235，提交 33d55d2）验收结果：PASS

- EXE：`D:\ZQ-Acceptance\acceptance-builds\20260919-2235\ZQ技术平台\ZQ技术平台.exe`
  （16,618,552 B，SHA256 `4c887f71a91371844e793dad324fc6bfe3b51ae4965e6b0302604d1e89af2bcc`）。
- 冒烟 PASS：client=0.2.10; schema=12；冻结包敏感文件扫描 0 命中；
  PYZ 字节码常量确认修复入包（material_analysis 含提示前缀、adapters/generation 含 user_role/DETAIL）。
- 实机验收（round11，全新 data14/settings14，真实模型，北京绵脉 5 文件）：
  - run c63a206cfa3b479c93e4b07b3cf7ce0d succeeded；自包含提示词一次直达计划，
    无需范围澄清、无需资料澄清（scope_answered=False, material_answered=False）。
  - 事件链：planning 已领取 → validating 全门过 → succeeded。
  - 产物 detail_workbook.xlsx 封面：被评估单位=北京绵脉科技有限公司，评估基准日=2026年6月30日。
  - 资料识别文案确认参考文件语义正确：银行-绵脉(1).xlsx"注明仅作参考资料，不作为填报依据"。
  - 五个原件 SHA256 前后一致。
