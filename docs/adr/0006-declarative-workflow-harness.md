# ADR 0006：声明式 Workflow Harness

- 状态：已接受（G06/G07 实施）
- 日期：2026-09-18

## 背景

当前 `harness.py`（88 行）是串行 DAG：原子 run 认领、逐步权限复核、事件存储、取消传播、unknown → reconciliation_required。`planner.compile_proposal` 把模型提案编译成版本绑定的 `ExecutionPlan`。缺口：无并行调度、无资源锁感知（Office/输出目录/浏览器页面/模型渠道）、无节点租约与追加式 Journal、无缓存键恢复、无节点级重试/退避、无独立验证节点、无统一阶段事件。

## 决定

1. 计划模型升级为声明式 `WorkflowPlan`：identity、turn_envelope_hash、plan_revision、budget、phases、nodes、edges、output_contract、acceptance_gates。节点类型限定为 understand / classify_materials / extract_evidence / model_call / run_skill / browser_action / validate_artifact / verify_business_result / ask_user / deliver。
2. 模型只提出节点与依赖；本地编译器验证类型、依赖、输入来源、输出契约、权限、预算、资源锁、Skill 版本和适配器；拒绝循环、孤立交付、未知工具、未选附件、跨项目路径、原件写入。
3. 运行时：DAG 就绪队列与可控并行；资源锁；调用/Token/余额/文件数/时间预算；节点超时、有限重试、退避、不可重试分类；父子取消树。
4. 追加式 Journal（run_created / node_claimed / node_progress / node_result_committed / node_failed / permission / resource / artifact / run_terminal）；缓存键含计划版本、节点、适配器、输入哈希、Skill/规则哈希、权限快照、依赖结果哈希。
5. unknown 一律进 reconciliation：模型任务按 client_job_id 对账，Office/浏览器写动作不自动重放。
6. 不执行模型生成代码（无 eval/exec/动态下载）。
7. 迁移纪律：旧 planner 输出经兼容适配层转换，新旧回归等价后再删旧入口；`harness.py` 不一次性重写。

## 替代方案

- 模型生成脚本沙箱执行（cc-haha 式 VM）：拒绝，业务范围用声明式 DAG 足够且可审计。
- 一次性重写 harness.py：拒绝，现有取消/对账语义是已验证资产。

## 后果

- 新增 `workflow_plan.py`、`workflow_compiler.py`（G06）、`workflow_runtime.py`、`workflow_journal.py`、`workflow_scheduler.py`、`workflow_events.py`、`workflow_reconciliation.py`（G07）。
- 既有审核、生成、浏览器任务必须经兼容层全部保持可用。

## 验收

- G06：恶意/错误计划均被本地拒绝；同一输入编译结果稳定。
- G07：进程中断恢复不重复扣费；同一 Office/输出目录无并发写；取消无僵尸 Worker；unknown 不盲目重放。
