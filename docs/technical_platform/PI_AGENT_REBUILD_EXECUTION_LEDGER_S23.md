# S23 执行账本：生产工具解析器、文件范围与浏览器接线

## 目标

让新 Agent 的 kernel、模型可见工具目录和 operation 资源快照使用同一套解析结果；把业务文件工具、Skill 工具和当前会话浏览器工具统一纳入 resolver，并为本轮文件写入建立默认项目范围。

## 根因

此前 `AgentGateway` 仅把 `active_tools()` 的临时列表交给 kernel，没有传入 `tool_resolver` 或 `FileScope`。因此资源快照为空、Skill 无法按 operation 固定版本恢复，文件策略的空范围等价于不做目录约束；浏览器虽可被列入目录，但未与 kernel 的解析链绑定。

## 修改

- 新增 `CompositeToolResolver`，组合 Skill Registry、业务 harness、浏览器 backend，并把 builtin 资源写入快照；恢复时只 pin Skill，重新装配同一组 builtin 工具。
- `AgentGateway._build_kernel()` 统一构造 resolver、业务工具和浏览器工具，向 kernel 注入 `tool_resolver` 与 `FileScope`。
- 默认 FileScope 覆盖平台数据库所在项目根及 `attachments/<project_id>`，避免写入类工具脱离项目目录。
- `ContextBuilder` 兼容 builtin 资源快照，只把 Skill 条目渲染为版本规则，避免把 builtin 条目当作 Skill 解包。
- 新增生产接线验收：resolver 非空、快照含 business/browser 来源、FileScope 非空、浏览器 backend 可执行。

## 验证

- 红灯：新接线测试在实现前因 `_build_kernel` 缺失失败（2 failed）。
- 目标回归：
  - `test_gateway_production_wiring.py`：4 passed（含既有 registry 接线测试）。
  - 完整 agent rebuild：385 passed，9 xfailed；S23 仅扩展快照装配，不改变既有快照字段。

## 未覆盖及后续

- Qt 应用生产工厂尚未创建并注入 SkillRegistry/真实 QWebEngine backend；本阶段完成 kernel 端口，不宣称 GUI 已完成。
- 生产 flags 的逐类别过滤需要在下一阶段把过滤策略也纳入 CompositeResolver，避免直接使用全量业务工具。
