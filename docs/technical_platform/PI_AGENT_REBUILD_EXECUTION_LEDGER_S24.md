# S24 执行账本：跨线程取消边界

## 目标

修复 UI 线程直接 `asyncio.run(kernel.abort())` 操作 worker 线程事件循环的问题，确保“停止”只发出同步取消信号，由拥有任务的 worker loop 完成持久化收束。

## 原因与位置

`AgentGateway.stop()` 在 Qt/UI 线程调用 `asyncio.run()`，而 `AgentKernel` 的取消 token、任务字典和异步 Task 属于提交线程的事件循环。该调用无法安全等待 worker loop 中的 Task，可能导致 UI 显示已停止但 operation 仍为 running，或跨 loop 清理异常。

## 修改

- `AgentKernel.cancel_open()` 新增同步取消入口，只触发当前 operation 的 `CancelToken`。
- `AgentGateway.stop()` 不再创建第二个事件循环或直接 await abort；把取消交给原 worker loop，使其按既有 `operation_aborted` 事务路径结束。
- 保留异步 `abort()` 供同一事件循环内恢复/测试路径使用。

## 验证

- 新增 `test_gateway_cancellation_thread.py`：跨线程入口只取消 token，不触碰 asyncio loop。
- Gateway、恢复、失败轮次回归：13 passed。
- S23 基线仍为 385 passed、9 xfailed；S24 变更尚未重新跑完整套件，下一阶段入口前必须补跑完整回归。
