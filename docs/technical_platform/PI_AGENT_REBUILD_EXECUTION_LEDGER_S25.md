# S25 执行账本：生产工具目录按权限灰度过滤

## 目标

避免 kernel 的 resolver 绕过 feature flags，向模型暴露未启用的业务或浏览器写入工具；保证 `active_tools()`、模型描述和 operation snapshot 使用同一目录。

## 根因与位置

S23 的 CompositeToolResolver 已接入 kernel，但初版直接以完整 `business_tools(service)` 和完整浏览器工具集构造 resolver。`AgentGateway.active_tools()` 虽然过滤了目录，kernel 接受 operation 时却重新解析成全量工具，形成 UI 目录与实际可调用能力不一致。

## 修改

- `_build_kernel()` 按当前 flags 过滤业务工具；浏览器只在 readonly 开关下提供读取/导航工具，写入上传工具还必须打开 `browser_write_upload`。
- 过滤后的业务工具作为 resolver `extra` 注入，避免再次从 service 重建全量工具。
- Composite resolver 为 builtin 组合工具写入稳定快照，恢复时重建同一 builtin 集合。

## 验证

- 新增浏览器写入开关测试；S25 接线测试 3 passed。
- 必须在交付下一阶段前运行全量 agent rebuild，确认 S24 的 388 passed、9 xfailed 基线未回归。
