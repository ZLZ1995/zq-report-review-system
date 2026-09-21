# S34 执行账本：Qt 浏览器 Agent 线程桥

## 问题

S32 只完成了 gateway 注入 seam；Agent worker 线程若直接操作 QWebEngine，容易
触发跨线程崩溃或 UI 卡死，且浏览器操作没有统一的 GUI 线程边界。

## 修改

- 新增 `browser_agent_backend.py::QtBrowserAgentBackend`。
- `BrowserPanel` 增加 queued Qt signal + `dispatch_agent_call`，所有网页操作从
  Agent 线程切换到面板 GUI 线程，并有超时和异常回传。
- 接入 `open`、`navigate`、`observe`、基于可见目标的 `click`/`fill`，网页脚本
  只回传有界结果。
- `upload`、`download`、`save_credential`、`use_credential` 不静默越过用户授权：
  分别要求接管或浏览器账号面板确认；断线/超时抛出可见后端错误。

## 验证

- 新增浏览器后端纯逻辑测试：2 passed。
- Agent rebuild 全量：`398 passed, 9 xfailed`。
- `browser_panel.py`、`browser_agent_backend.py`、`app.py` 静态编译通过。

## 未完成边界

真实 QWebEngine Windows 环境尚未做人工点击、登录、下载和上传验收；下载/上传/
凭据端口仍是显式接管边界，不能宣称 OA 自动化已完成。
