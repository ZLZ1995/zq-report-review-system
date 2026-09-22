# S33 执行账本：全会话 Agent 生命周期收束

## 问题

权限模式切换和窗口关闭原先只处理旧 TaskManager；新 Agent 的多个会话
`_agent_jobs` 不在该集合中，可能继续运行、继续访问模型或在窗口切换后留下后台
线程。

## 修改

- 权限模式切换遍历所有 Agent jobs，调用各自 gateway.stop，并计入停止数量。
- `closeEvent` 在所有 Agent jobs 终止前拒绝关闭，避免 SQLite/Qt 对象被后台线程
  使用；最后一个 job 完成后自动重新触发关闭。
- 后台会话 worker 结束时同样参与关闭判定，当前会话切换不会遗漏。

## 验证

- UI/多会话测试：17 passed。
- Agent rebuild 全量：`396 passed, 9 xfailed`。
- 相关模块静态编译通过。

## 边界

真实浏览器 GUI 端口、云端联调、Office/WPS 实机仍未验收；本阶段只闭合 Agent
job 的本地生命周期。
