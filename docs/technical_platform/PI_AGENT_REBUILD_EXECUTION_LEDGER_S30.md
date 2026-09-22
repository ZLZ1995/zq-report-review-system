# S30 执行账本：按会话隔离 Agent Worker

## 问题

客户端原先只有一个全局 `_agent_worker`、`_agent_session_id` 和一组 live
文本。切换会话会覆盖这些变量；停止、增量渲染和完成回调可能落到当前选中
会话，导致 A 会话的运行状态、回复或文件成果显示在 B 会话下。

## 修改

- `app.py` 增加 `_agent_jobs[session_id]`，保存 worker、gateway、operation_id、
  user_text、live_text 和 done 状态。
- Worker 信号通过带 session 闭包的回调进入 `_on_agent_*_for`，回调只更新其
  所属会话；`_agent_worker` 仅作为当前会话兼容别名。
- 切换会话时从对应 job 恢复输入态、运行态和 live 文本；其他会话继续运行，
  不再被覆盖。
- 完成回调先标记 job done，再刷新当前会话，避免终态之后残留“正在生成”卡。
- 原有无 repo 测试网关保留 legacy 回退；生产新 Agent 仍只使用持久化 repo。

## 验证

- 新增 `ui/test_per_session_agent_workers.py`：两个会话同时运行、切换、分别
  收束，回复不串线。
- UI/接线测试：19 passed。
- Agent rebuild 全量回归：`394 passed, 9 xfailed`。

## 边界

真实 Windows 多窗口和异常退出恢复仍需后续实机验收；当前阶段只确认同一 Qt
进程内的多会话 worker 隔离。
