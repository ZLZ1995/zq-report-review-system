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
- [ ] S2-01 执行 Lease
- [ ] S2-02 Tool Recovery Policy
- [ ] S2-03 客户端/服务端请求对账接口

## S3 服务端计费与流式一致性
- [ ] S3-01 AgentCompletionService terminal guard
- [ ] S3-02 canonical replay payload（修复 2000 事件截断）
- [ ] S3-03 ReviewJob 与 Hold 一致性
- [ ] S3-04 Provider SSE 严格协议校验

## S4 不可信输入与本地安全边界
- [ ] S4-01 Skill ZIP 安全重写
- [ ] S4-02 Provider Route URL / SSRF 防护
- [ ] S4-03 Tool Schema 限制

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
- 存量问题：根目录 3 个 test_detail_*.py 缺 test_detail_workbook_pipeline_guards 模块，HEAD 即无法收集（留 S8）

阶段结论：
- S1 已完成（2026-09-22）：17 项验收测试全绿，全量回归无新增失败；阶段报告见 remediation/s1/STAGE_REPORT.md
- S2 待开始
