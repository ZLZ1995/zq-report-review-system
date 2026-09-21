# 总控模型清单选择验收

## 操作流程

1. 管理员填写 HTTPS API URL 和 API Key。
2. 点击“测试连接”，服务端仅请求标准 `/models` 清单，不发起聊天生成。
3. “所属模型”显示清单，保留空白选择项，由管理员手动选择一个模型。
4. 确认渠道单价后保存；平台自动创建相应模型记录，不必提前手动新增模型。
5. 修改 URL 或 Key 后清单失效，必须重新测试。测试凭证有效期 15 分钟。

官方 DeepSeek 域名自动标记 DeepSeek，其余公网 HTTPS 地址标记为兼容渠道，不声称验证真实供应商。既有模型/渠道接口保留兼容。

## 安全与边界

- 仅管理员可测试和保存。API Key 不回显、不写入日志、不随测试保存到数据库。
- 服务端校验公网 IP，并将连接固定到已校验 IP，同时保留 TLS 主机名验证，不跟随重定向。
- 仅支持 443 端口及标准 `data[].id` 清单。显式分页清单会报不支持，不能声称已经取得全部模型。
- 测试失败不生成候选项；响应异常、空清单、鉴权失败和限流均有提示。
- 清单成功不证明模型生成能力或计费准确，真实调用验收需单独进行。
- 单价不从模型名称猜测，仍由管理员确认。
- 本次不修改已有账号余额、API Key 或已保存渠道。

## 验证

运行 `python -m pytest tests/report_review_server -q`。
运行 `node tests/report_review_server/test_admin_discovery_ui.cjs`（无额外 npm 依赖）。

云端发布需同步 `admin_web.py`、`api.py`、`services/model_discovery.py`、`admin_assets/index.html` 和 `admin_assets/app.js`，无需数据库迁移或新环境变量。部署后页面刷新会清除管理员会话，需要重新登录。
