# ADR 0002：TurnEnvelope 与附件范围

- 状态：已接受（G01 实施）
- 日期：2026-09-18

## 背景

当前轮附件范围已经绑定到任务：`AgentController.prepare` 只接受调用方传入的 `selected_ids` 并逐一核对项目文件与哈希；`execution.execute_task` 复核快照 `files`/`selected_files`/`file_scope`；`freeze_scope` 冻结范围。但"当前轮"的事实分散在多个调用参数里：选中 ID 列表、消息文本、模型 ID、权限模式、分支上下文各自传递，会话切换或附件变化后的失效判断分散在 `_current`、`complete` 等多处。迟到理解结果的防护依赖逐点检查，没有一个单一不可变对象承载"这一轮"。

## 决定

1. UI 提交消息时一次性生成不可变 `TurnEnvelope`：schema_version、owner/project/session/turn/message ID、raw/normalized 文本、明确引用、选中附件版本、新附件、历史引用、排除项、模型、权限模式、澄清链、提交时间、content_hash。
2. 理解、规划、执行、恢复只传 envelope 引用（ID/hash），不重新扫描会话附件。
3. 附件替换/删除、会话切换、权限或模型变化使旧理解结果失效（继承并集中现有 `_current`/`complete` 的逐点检查）。
4. 当前轮明确提到的文件名与选中附件不一致时进入澄清。
5. UI 展示"本轮资料范围"摘要。

## 替代方案

- 维持分散参数：拒绝，失效判断的完备性无法集中证明。
- 服务端生成 envelope：拒绝，范围事实属于客户端本地可信边界。

## 后果

- 新增 `turn_context.py`、`turn_normalizer.py`、`turn_scope_policy.py`、`input_gateway.py`（G01）。
- `UnderstandingRequest` 保留为线上协议；envelope 先作为其本地生成来源，服务端协议不变。
- 硬指标：未选历史附件进入任务 = 0。

## 验收

- G01：≥40 项边界测试（新/旧附件、同名不同版本、替换、删除、重命名、分支继承、会话切换、迟到结果、取消后恢复），误带旧文件为 0。
