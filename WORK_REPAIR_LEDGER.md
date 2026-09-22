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
- [ ] S5-01 文件导入事务化
- [ ] S5-02 CredentialVault 并发修复
- [ ] S5-03 损坏项目可见
- [ ] S5-04 统一旧 Task interrupted 状态

## S6 客户端 UI / 多会话稳定性
- [ ] S6-01 每会话独立 live render state
- [ ] S6-02 优雅关闭

## S7 认证与安全加固
- [ ] S7-01 客户账号密码策略
- [ ] S7-02 Refresh Token Rotation / Reuse Detection

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
- 存量问题：根目录 3 个 test_detail_*.py 缺 test_detail_workbook_pipeline_guards 模块，HEAD 即无法收集（留 S8）；services 层 browser_step/client_release_service/task_planning/task_understanding 存量 I001（留 S8）；api.py 67 处 B008（FastAPI 惯例，改动前后均为 67，零新增）

阶段结论：
- S1 已完成（2026-09-22）：17 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s1/STAGE_REPORT.md
- S2 已完成（2026-09-22）：lease/恢复策略/对账接口全部落地，26 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s2/STAGE_REPORT.md
- S3 已完成（2026-09-22）：terminal guard/canonical replay/hold 对账/SSE 严格校验全部落地，27 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s3/STAGE_REPORT.md
- S4 已完成（2026-09-22）：ZIP 安全/SSRF/Tool Schema 全部落地，40 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s4/STAGE_REPORT.md
