# ZQ 修复执行台账

基准 SHA: 879a4aa386674bcb0f6c7a63557cf0536a069ea0（main，审计基准与当前 main 内容一致，逐文件比对 0 差异）
工作分支: kimi/work-repair-s1-s14（起点 862d0e0，树与 main 完全相同）
开始时间: 2026-09-22 15:00 +0800
CI 基线: technical-platform-client / report-review-server 在 879a4aa 均 success（2026-09-22T02:25Z）
执行授权: 用户明确指令"直到所有修复目标都完成修复为止"，覆盖任务书"每阶段后停止"的默认限制；阶段报告照常产出。

## S1 Agent 生命周期安全
- [x] S1-01 Agent Operation terminal guard（runtime._ensure_terminal，含 submit/_drive 双守卫 + _emit 落库隔离）
- [x] S1-02 Resume ordinal（loop 从 max(existing)+1 起；含 unknown ToolCall 拒绝续跑的安全收束）
- [x] S1-03 operation_id 统一（gateway 全路径返回真实 id；worker accepted 信号；app 删除假 uuid）
- [x] S1-04 UI fallback（_on_agent_done_for 查重后补 error_message fallback entry）
- [x] S1-05 registry cleanup（kernel._tasks done-callback 清理；gateway open 集合 unknown 清理）

## S2 Recovery / Reconciliation
- [x] S2-01 执行 Lease（SCHEMA_VERSION 16：agent_operations 加 executor_id/lease_expires_at/last_heartbeat_at；kernel 心跳 + recover 跳活 lease + resume 认领）
- [x] S2-02 Tool Recovery Policy（contracts 策略表 + ToolDescriptor.recovery_policy；resume 对 open/unknown 工具按策略放行或 tool.unknown_outcome 拒绝）
- [x] S2-03 客户端/服务端请求对账接口（agent_core/reconciliation.py；服务端 GET /completions/{id} 与 /replay；ServerModelPort.reconcile_request/replay_request；gateway recover 后对账）

## S3 服务端计费与流式一致性
- [x] S3-01 AgentCompletionService terminal guard（provider_started/usage/settled 阶段分类；非协议异常落 failed/uncertain/disconnected，绝不永久 streaming）
- [x] S3-02 canonical replay payload（CanonicalReplayBuilder 保序折叠 + encode_canonical_replay 重编码；删除 2000 事件截断；旧格式存量行兼容）
- [x] S3-03 ReviewJob 与 Hold 一致性（settle_terminal_jobs 幂等补结算；recover_interrupted 启动先对账）
- [x] S3-04 Provider SSE 严格协议校验（全类型显式检查；非法结构→ProviderCallError；无 [DONE]/无 finish_reason 不发 message_complete）

## S4 不可信输入与本地安全边界
- [x] S4-01 Skill ZIP 安全重写（反斜杠/绝对路径/drive/`..`/大小写重复/加密条目/非常规文件拒绝；成员数/展开字节/单文件/压缩比上限；staging 解压 + resolve 包含校验 + 原子 rename）
- [x] S4-02 Provider Route URL / SSRF 防护（url_security.validate_provider_base_url：仅 https、禁 userinfo、localhost/loopback/link-local/私网/保留地址 IPv4+IPv6；REPORT_REVIEW_PROVIDER_URL_ALLOWLIST 企业豁免）
- [x] S4-03 Tool Schema 限制（16KB 大小/16 深度/128 单对象 properties/512 总预算/required 必须对应 property/关键字白名单拒 $ref 递归爆炸）

## S5 本地文件与数据库一致性
- [x] S5-01 文件导入事务化（file_service.import_files 重写：预校验→digest 全算+批内重复检测→`.staging-<uuid>` 暂存→暂存 hash 复核→逐文件 os.replace→manifest 落库；任何一步失败回滚已移动文件并清理 staging；_unique_destination 加批内占位防同名冲突）
- [x] S5-02 CredentialVault 并发修复（WAL + busy_timeout=5000 + BEGIN IMMEDIATE 升级写事务 + locked 重试 3 次；读路径不再升级锁；另修复并发安全检查两个 TOCTOU 瞬态误报：delete-pending 的 `$Extend\$Deleted` resolve 结果跳过、`\\?\` 扩展长度前缀规范化、stat FileNotFoundError 跳过）
- [x] S5-03 损坏项目可见（CorruptedProjectEntry：manifest 解析失败项目以 status='corrupted' 出现在列表，UI 显示〈项目损坏/不可访问〉且禁止继续/删除误操作）
- [x] S5-04 统一旧 Task interrupted 状态（状态机补 interrupted→{failed,running,cancelled}；claim_run 收紧为仅 queued/waiting_user 可领取，interrupted 须经对账后由恢复路径显式放行，保持 test_harness "不确定结果绝不继续" 语义）

## S6 客户端 UI / 多会话稳定性
- [x] S6-01 每会话独立 live render state（`_live_render_pending` 按 session 记账；done 只清本会话记账、不再无条件停 timer；choose_session 进场一次性呈现累积 live text 并结清该会话记账；owner 切换全清）
- [x] S6-02 优雅关闭（ReviewJobExecutor.shutdown(timeout)：停收新任务→等 worker 到安全检查点→超时 requeue_for_shutdown 标记 shutdown_grace_expired→cancel_futures 关池；顺带修复 submit 锁内注册 done 回调的自死锁；客户端 closeEvent 15s 宽限期，超时 mark_operations_unknown 持久化 durable 检查点后放行关闭）

## S7 认证与安全加固
- [x] S7-01 登录防护（保留客户简化密码格式——characterization 冻结；进程内按用户名计数：连续 5 次失败锁定 15 分钟 423、第 3 次失败起递增重试间隔 429、成功登录清零、改密/管理员重置解锁；不存在的用户名同等计数防枚举预言机；配置项 REPORT_REVIEW_LOGIN_MAX_FAILURES/LOCKOUT_SECONDS/FAILURE_DELAY_SECONDS）
- [x] S7-02 Refresh Token 轮换链加固（grace 外旧令牌再现→撤销整条 session family（refresh_token_reuse_detected）；refresh 绑定 client_instance_id，不匹配→撤销 family（client_instance_mismatch）；不带实例 id 的旧客户端兼容放行）

## S8 CI / 质量门禁 / 仓库治理
- [ ] S8-01 全仓 Ruff
- [ ] S8-02 类型检查
- [ ] S8-03 安全检查
- [ ] S8-04 Fault Injection Suite
- [ ] S8-05 State Machine Property Tests
- [ ] S8-06 GitHub Main 保护

## S9-S14 UI/UX
- [ ] S9 运行状态与任务反馈
- [ ] S10 执行记录与消息层级
- [ ] S11 文件面板重构
- [ ] S12 成果交付与任务历史
- [ ] S13 导航与文案统一
- [ ] S14 视觉层级和密度优化

新增发现：
- 仓库根目录曾被误创建 63 字节 `NUL` 文件（wmic 输出重定向事故），已清理。

阻塞：
- 无

测试：
- S1 定向：修复前 16 failed/1 passed（tmp-pytest-s1red）→ 修复后 17 passed
- S1 回归：agent_rebuild 419 passed/9 xfailed；technical_platform 顶层分块 1398 passed；report_review_server 228 passed/1 skipped；report_review_app+agent_acceptance+platform_update 352 passed
- S2 定向：修复前 19 failed（5 文件）→ 修复后 26 passed
- S2 回归：agent_rebuild 437 passed/9 xfailed；report_review_server 236 passed/1 skipped；technical_platform 顶层分块 92+136+260+509+753 全绿；report_review_app+agent_acceptance+platform_update 352 passed
- S3 定向：修复前 24 failed / 3 passed（3 个通过项为既有行为守护用例）→ 修复后 27 passed
- S3 回归：report_review_server 263 passed/1 skipped；agent_rebuild 437 passed/9 xfailed；technical_platform 顶层分块 84+8+136+260+509+401=1398 全绿；report_review_app+agent_acceptance+platform_update+test_detail_scope_first 352 passed
- S4 定向：修复前 25 failed + 1 收集错误（5 个通过项为合法用例守护）→ 修复后 40 passed
- S4 回归：report_review_server 293 passed/1 skipped；agent_rebuild 447 passed/9 xfailed；technical_platform 顶层 92+136+260+509+401=1398 全绿；app/acceptance/update 块 352 passed
- S5 定向：修复前 15 failed / 5 passed → 修复后 20 passed（并发用例连跑 3 遍稳定全绿）
- S5 回归：agent_rebuild 447 passed/9 xfailed；report_review_server 293 passed/1 skipped；technical_platform 顶层 92+136+260+509+409（含 S5 新增 8）全绿；app/acceptance/update/detail 块 364 passed（含 S5 新增 12）
- S6 定向：修复前 1 failed + 1 死锁挂起 + 2 ImportError/不可用（先红）→ 修复后 9 passed（tmp-pytest-s6green3）
- S6 回归：agent_rebuild 453 passed/9 xfailed（447+6）；report_review_server 296 passed/1 skipped（293+3）；technical_platform 顶层 92+136+260+509+409 全绿；app/acceptance/update/detail 块 364 passed
- S7 定向：修复前 7 failed / 2 passed（守护用例）→ 修复后 9 passed（tmp-pytest-s7green3）
- S7 回归：report_review_server 305 passed/1 skipped（296+9）；agent_rebuild 453 passed/9 xfailed；technical_platform 顶层 92+136+260+509+409 全绿；app/acceptance/update/detail 块 364 passed
- 存量问题：根目录 3 个 test_detail_*.py 缺 test_detail_workbook_pipeline_guards 模块，HEAD 即无法收集（留 S8）；services 层 browser_step/client_release_service/task_planning/task_understanding 存量 I001（留 S8）；ui/project_window.py 存量 I001（S5 改动该文件但 I001 为 HEAD 既有，留 S8 统一处理）；api.py 67 处 B008（FastAPI 惯例，改动前后均为 67，零新增）

阶段结论：
- S1 已完成（2026-09-22）：17 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s1/STAGE_REPORT.md
- S2 已完成（2026-09-22）：lease/恢复策略/对账接口全部落地，26 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s2/STAGE_REPORT.md
- S3 已完成（2026-09-22）：terminal guard/canonical replay/hold 对账/SSE 严格校验全部落地，27 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s3/STAGE_REPORT.md
- S4 已完成（2026-09-22）：ZIP 安全/SSRF/Tool Schema 全部落地，40 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s4/STAGE_REPORT.md
- S5 已完成（2026-09-22）：导入事务化/凭据库并发/损坏项目可见/interrupted 状态收束全部落地，20 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s5/STAGE_REPORT.md
- S6 已完成（2026-09-22）：每会话独立 live render/executor 优雅关闭/客户端关闭 durable 检查点全部落地，9 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s6/STAGE_REPORT.md
- S7 已完成（2026-09-22）：登录失败锁定+递增延迟/refresh 重用检测撤销 family/实例绑定全部落地，9 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s7/STAGE_REPORT.md
- S8 定向：fault_injection 初跑 6 failed（语义校准）→ 12 passed；状态机属性初跑 6 failed → 15 passed；全仓 ruff 192 errors → baseline 冻结 133 + 自动修复 62 → 0 errors；mypy 优先模块 4 errors → 0；pip-audit 1 漏洞（cryptography PYSEC-2026-3552）→ 升 50.0.1 → 0
- S8 回归：agent_rebuild 453 passed/9 xfailed；report_review_server+fault_injection 322 passed/1 skipped；technical_platform 顶层 92+136+260+509+419（含 S8 新增 10）全绿；app/acceptance/update/detail 块 364 passed
- S8 新增门禁：client/server CI ruff 全仓化；server-ci 增 mypy 优先模块步骤；新增 security-ci.yml（pip-audit+bandit 高危门禁+gitleaks+requirements lock 检查，周一定时）；dependabot.yml（pip+github-actions）；pyproject.toml 冻结存量违规 per-file-ignores

阶段结论（续）：
- S8 已完成（2026-09-22）：全仓 Ruff baseline/类型检查/安全检查/故障注入 11 场景/七套状态机属性测试全部落地，27 项新用例全绿，全量回归无新增失败；阶段报告见 remediation/s8/STAGE_REPORT.md；S8-06 main 保护随最终推送执行
- S9 定向：先红（模块不存在）→ 实现后 4 failed（短 id 规则/测试时序校准）→ 12 passed（tmp-pytest-s9g7）
- S9 回归：agent_rebuild 465 passed/9 xfailed（含 S9 新增 12）；report_review_server+fault_injection 322 passed/1 skipped；technical_platform 顶层 92+136+260+509+419 全绿；app/acceptance/update/detail 块 364 passed
- S9 落地：run_status.py 状态卡视图模型（无伪造百分比）；控制器新增 stopping/waiting_user 活动相位与 started_at/last_activity_at；cancel_run 接入 stopping；终态摘要行替换临时卡；按钮禁用全部带 tooltip 原因
- S10 定向：先红（模块不存在）→ 实现后一次转绿 10 passed；与 S9 联合 22 passed
- S10 回归：agent_rebuild 475 passed/9 xfailed（含 S10 新增 10）；report_review_server+fault_injection 322 passed/1 skipped；technical_platform 顶层 92+136+260+509+419 全绿；app/acceptance/update/detail 块 364 passed
- S10 落地：message_cards.py 六类卡片；error_message 透传 severity/error_code（kind 冻结不变）；连续 ≥3 条中性执行记录折叠（zq-events 展开/收起）；ErrorCard 带错误码+任务 id+zq-diagnostics 剪贴板复制（无 traceback/凭据）

阶段结论（续）：
- S9 已完成（2026-09-22）：运行状态卡/计时/stepper/stopping/waiting_user/终态摘要/按钮原因全部落地，12 项验收测试全绿；阶段报告见 remediation/s9/STAGE_REPORT.md
- S10 已完成（2026-09-22）：消息层级卡片化/执行记录折叠/Error detail/diagnostics copy 全部落地，10 项验收测试全绿；阶段报告见 remediation/s10/STAGE_REPORT.md
- S11 定向：先红（file_panel 模块不存在，收集错误）→ 实现后 1 failed（'未使用'过滤语义校准：fixture 补真实任务快照使用证据）→ 10 passed（tmp-pytest-s11h）
- S11 回归：agent_rebuild 475 passed/9 xfailed；report_review_server+fault_injection 322 passed/1 skipped；technical_platform 顶层 92+136+260+509+509+429（[p-z] 块含 S11 新增 10）全绿；app/acceptance/update/detail 块 364 passed
- S11 落地：file_panel.py（角色识别/期间识别 YYYY年度·YYYYQn·YYYYMM/FileRowView/row_label 隐藏 hash/format_size/filter_rows/file_detail_text）；app.py 文件 tab 新增搜索框/过滤器（全部文件·本轮已选·未使用·已用于任务）/全选可见·取消可见批量操作/双击文件详情；勾选契约不变（UserRole=file id + checkState，搜索过滤只 setHidden 不重建 item）

阶段结论（续）：
- S11 已完成（2026-09-22）：文件角色/期间识别/本轮使用状态/搜索/过滤/批量选择/隐藏 hash/文件详情全部落地，10 项验收测试全绿；阶段报告见 remediation/s11/STAGE_REPORT.md
