# S31 执行账本：旧会话消息镜像与上下文连续性

## 问题

旧客户端把消息写在 legacy `store.messages`，新 Agent 的
`ContextBuilder` 只读 `conversation_entries`。旧会话虽能在 UI 显示，模型却看
不到历史提问和回答；同时 UI 双投影还可能把旧成果错误挂到新回复。

## 修改

- `AgentGateway._mirror_session` 在会话元数据镜像后读取 legacy 消息，按角色
  映射为 `user_message`、`assistant_message`、`event`。
- 每条迁移 entry 写入 `_legacy_message_id` 标记；重复 gateway 初始化/提交只
  跳过已迁移 ID，保持幂等，不影响新 Agent 原子写入的 operation entry。
- UI 时间线保留历史成果块，但只去除旧消息的重复文本；成果不再以新 Agent
  回复为锚点，避免“之前文件挂在新回复下”。

## 验证

- 新增网关幂等镜像测试：首次得到 user/assistant 两条，第二次数量不变。
- 网关恢复、时间线和上下文相关目标测试：16 passed。
- Agent rebuild 全量：`395 passed, 9 xfailed`。
- `app.py`、`conversation_timeline.py`、`agent_gateway.py` 静态编译通过。

## 边界

历史附件尚未自动绑定到每一次新 operation；当前仍遵守“本轮明确选择/上传才
进入文件范围”的安全规则。后续需增加基于自然语言指代的候选文件确认/绑定，
并继续做真实资料复测。
