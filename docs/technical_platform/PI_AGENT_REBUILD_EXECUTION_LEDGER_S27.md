# S27 执行账本：模型流终止协议

## 目标

禁止模型流在没有明确终止事件时被当作成功回答，避免网络断流/协议截断后 UI 出现空回复、旧回复复用或任务状态错误完成。

## 原因与位置

`agent_core/loop.py::_run_turn` 原先在异步流返回 `None` 后直接继续收束：只要没有 tool call，就会提交 assistant_message 并完成 operation。模型端若在 `message_complete` 前断流，partial 文本会被错误标记为完整结果。

## 修改

- 跟踪 `message_complete` 事件。
- 流结束前未收到该事件时抛出 `ModelProtocolError`，由上层统一落 `error_message`、失败 turn 和 `operation_failed`。
- 保留 `thinking_delta` 等已声明事件的忽略行为；协议事件本身由 `ModelEvent` 合同校验。

## 验证

- 新增无终止事件失败测试：1 passed。
- core loop 全套：31 passed。
- 下一阶段入口前需完成全量 agent rebuild 回归。
