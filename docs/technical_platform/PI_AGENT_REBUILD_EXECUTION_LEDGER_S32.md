# S32 执行账本：生产浏览器后端注入边界

## 问题

AgentGateway 已具备浏览器 Tool 端口，但客户端 `_make_agent_gateway` 原先不
读取当前浏览器面板，生产路径始终落到 `NullBrowserBackend`；模型即使获得
`browser_*` 工具也只能得到“后端未接线”。

## 修改

- `app.py::_make_agent_gateway` 从当前面板读取可选的
  `agent_backend`，作为 `browser_backend` 注入 AgentGateway。
- 没有打开浏览器或面板尚未提供端口时继续使用安全的 NullBackend，不自动拉起
  浏览器、不把 OA 绑定为首页。
- 生产接线测试覆盖 active backend 的依赖注入，避免 UI 仅显示浏览器而 Agent
  仍使用空后端。

## 验证

- 新增生产装配测试：浏览器面板提供 backend 时，gateway 持有同一实例。
- Agent rebuild 全量：`396 passed, 9 xfailed`。
- 相关模块静态编译通过。

## 未完成边界

当前 Qt `BrowserPanel` 尚未实现完整 `agent_backend` 端口（observe/click/fill/
upload/download/credential 的 GUI 线程桥仍需后续阶段完成）；本阶段只完成生产
注入 seam，不能宣称浏览器 Agent 操作已部署可用。
