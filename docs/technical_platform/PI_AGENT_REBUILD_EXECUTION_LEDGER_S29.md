# S29 执行账本：Agent 会话时间线与重复渲染修复

## 问题与原因

生产 UI 同时读取 legacy `store.messages` 和新 Agent 的 SQLite
`conversation_entries`。提交时 `_try_agent_submit` 又写入一份 user，完成时
`_on_agent_done` 再写入一份 assistant；而新 Agent 内核已经在
`begin_operation`/turn 收束时原子持久化同样的 entry，造成回复重复、旧成果
挂到新回复以及失败轮次显示陈旧内容。

## 修改位置

- `conversation_timeline.py`：新增 `project_agent_timeline`，只投影
  `user_message`、终态 `assistant_message` 和 `error_message`；忽略
  `tool_call`、`tool_result`、中间 assistant 文本；支持临时 user/live 状态。
- `app.py::_try_agent_submit`：生产 Agent 不再写 legacy user；仅无 `repo`
  的测试/兼容网关使用回退写入。
- `app.py::_on_agent_done`：生产 Agent 不再追加 legacy assistant；状态控制器
  只负责轮次状态。
- `app.py::render_messages`：读取当前 session/main lane 的 Agent entries，
  与旧时间线合并时移除相同的灰期消息及其锚定成果，避免同一回复出现两处。
- `_render_timeline_item`：新增待发送用户消息的对话区投影。

## 验证

- 新增 `ui/test_agent_timeline_projection.py`：终态唯一投影、内部事件隐藏、
  失败事件可见、待发送消息位置四项覆盖。
- UI wiring + 新测试：18 passed。
- Agent rebuild 全量：`393 passed, 9 xfailed`。
- 生产 EXE 构建基线 S28 不变；本阶段尚未发布云端或覆盖正式安装包。

## 未完成边界

历史 legacy 消息仍需在后续迁移/清理阶段建立永久映射；本阶段只保证新 Agent
提交不再产生双写，并在 UI 投影层隔离已有完全重复项。真实 Windows UI、
Office/WPS、浏览器和 Zeabur 联调仍需单独验收。
