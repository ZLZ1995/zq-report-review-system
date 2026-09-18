# ADR 0001：Agent 分层与本地可信边界

- 状态：已接受（方向性决定，目标实现随 G01–G08 渐进落地）
- 日期：2026-09-18

## 背景

当前 Agent 是一个职责集中的链路：`AgentController`（理解生命周期）+ `RoutingWorker`/`UnderstandingWorker`（网络调用）+ `planner.compile_proposal`（本地编译）+ `harness`/`execution`（执行）。模型输出经 `validate_understanding` / `validate_proposal` 双侧校验，`ToolDispatcher` 只分派已注册适配器，`PermissionService` 回执由可信 UI 签发。安全属性已经成立，但理解、路由、计划、执行、验证、记忆六类职责的上下文和工具边界没有显式分离，验证常与执行同源。

## 决定

1. Agent 按六层职责建模：Conversation、Intent Analyst、Capability Router、Plan Compiler、Domain Executor、Independent Verifier；浏览器任务另有 Browser Operator；记忆侧另有 Memory Curator（只产候选，无业务写权限）。
2. 分层是上下文与工具池的边界，不是进程数量：简单任务保持单执行链路，只有并行、独立验证、上下文超限时才拆分。
3. 本地可信边界保持不变：模型只能提出结构化意图/计划；编译、权限、执行、验证全部由本地代码完成。任何模型文本不产生授权。
4. 不迁移技术栈（继续 Python/PySide6），不引入模型生成代码执行。

## 替代方案

- 全能单 Agent + 提示词约束：拒绝，职责边界无法审计。
- 每职责独立进程：拒绝，当前任务体量不需要，进程边界会放大恢复与取消复杂度。
- Electron/TypeScript 重写：拒绝，既有 PySide6/Office COM 与测试资产是核心价值。

## 后果

- 新增 `agent_profiles.py`（G08）定义各 Profile 的可读上下文、允许工具、禁止数据、输出 schema 和预算。
- 现有 `agent_controller.py`、`harness.py` 不重写，通过适配层渐进映射到 Profile 契约。
- 测试需覆盖：Verifier 无写权限、Curator 无业务文件权限、Browser Operator 不得读取凭据明文。

## 验收

- G08 验收：简单任务不额外拆 Agent；故意制造的公式/版式/哈希/模板/回执错误均被 Independent Verifier 拦截。
- 现有 920 项平台回归在迁移全程保持通过。
