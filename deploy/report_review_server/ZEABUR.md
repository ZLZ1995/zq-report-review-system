# Zeabur 单实例演示部署

此仓库快照仅包含后端和Web总控，不包含客户文档、密钥、桌面EXE或本地数据库。
生产正式验收仍待完成，不应直接接入真实付费客户。

1. 同一Zeabur项目添加PostgreSQL服务，使用私有网络连接。
2. 添加GitHub服务，选择本仓库main分支，根目录 `/`。
3. 设置 `ZBPACK_DOCKERFILE_PATH=deploy/report_review_server/Dockerfile`。
4. 配置以下变量，并保持一个副本。当前审核执行器使用数据库抢占和进程内单工作线程；
   启动时会恢复上一进程遗留的运行任务，但尚未支持多个服务副本同时调度：

| 变量 | 值 |
|---|---|
| REPORT_REVIEW_ENV | production |
| REPORT_REVIEW_BUILD_SHA | 每次正式部署前填写本次完整的40位小写Git提交SHA。不要在运行时填写字面量 `${ZEABUR_GIT_COMMIT_SHA}`；当前Zeabur Docker部署不会展开它。该值为公开元信息，不能填写密钥。 |
| REPORT_REVIEW_DATABASE_URL | postgresql+psycopg://用户:URL编码密码@私网主机:端口/数据库 |
| REPORT_REVIEW_JWT_SECRET | secrets.token_urlsafe(48)生成的独立随机值 |
| REPORT_REVIEW_PROVIDER_ENCRYPTION_KEY | base64.urlsafe_b64encode(secrets.token_bytes(32)).decode()生成的独立值 |
| REPORT_REVIEW_ADMIN_USERNAME | 首次管理员账号 |
| REPORT_REVIEW_ADMIN_PASSWORD | 首次管理员强密码，至少12字符 |

PORT读取Zeabur注入值，未提供时8000。不要在仓库中保存真实变量。
JWT与加密密钥必须安全备份；已有数据库必须保留旧加密密钥。
启动时自动迁移数据库；当前数据库版本包含 `0006_review_job_events`，用于持久保存不含
文档正文和模型输出的审核进度事件。配置管理员变量时执行初始化。失败则终止启动。
首次初始化成功后删除管理员账号/密码两个变量并重新部署，防止长期保留初始密码。
不要同时启动多个执行迁移的副本。将来扩容前需将迁移改为独立发布步骤。

5. 绑定HTTPS域名，访问 `/api/v1/health` 应返回status=ok；访问
   `/api/v1/capabilities` 应返回本次完整提交SHA，并包含 `review_events: 1`、
   `agent_completion_stream: 1`。新 Agent 客户端只接受该能力声明；缺少时不会
   回退旧 Agent，也不会发起模型请求。
   使用已登录客户端或受控探活确认 `POST /api/v1/agent/completions/stream`
   不再返回404，并完成一次SSE、余额预检、计费回执、重复请求幂等和取消对账验收。
6. 访问 `/admin` 登录总控，创建模型渠道、客户账号并调整余额。
7. 客户端服务地址填 `https://域名/api/v1`，不是供应商地址。

审核启动接口以HTTP 202受理，客户端随后轮询任务并可通过
`/api/v1/review-jobs/{job_id}/events?after_sequence=N` 增量恢复进度。事件只含状态和批次计数；
原文、提示词、模型输出、费用和密钥不得进入事件表。

仅总控和计费API上线并不代表完整产品验收：多副本执行、外部干净Windows环境、
计费幂等操作界面以及完整浏览器端验收仍需进一步验证。
总控当前与后端共用域名，必须限制管理员访问与妥善保管凭据。
