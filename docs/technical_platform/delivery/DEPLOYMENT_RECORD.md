# 部署记录

## 2026-09-16 容器只读查询补充（优先于下方早期未知状态）

- Zeabur目标服务仍1/1运行，main，Release 0.2.5；本次从运行中部署详情核实ID为6aa9225fd3687c7a2564b4f1，域名PROVISIONED。
- 从该服务“命令”入口进入容器，终端提示工作目录/app。只读执行 `python -m alembic -c deploy/report_review_server/alembic.ini current`，屏幕明确返回 `0003_review_jobs (head)`（PostgresqlImpl）。这证明实际数据库修订与当前镜像迁移头一致，不是以本地文件推断。
- 上述核查时本地迁移目录只有0001_auth、0002_billing、0003_review_jobs。后续本地新增0004_billing_reconciliation（down_revision=0003_review_jobs），已在SQLite合成库验证增量升级与审计保留降级门禁；未推送、未在生产执行，不能把本地head当成线上状态。
- 页面备份开关仍关闭且未列历史记录；未执行备份、还原、升级、重启或更改配置。镜像摘要/精确构建SHA仍待单独证明，发布说明不是镜像哈希。
- 终端多行输入尝试未产生可见执行结果，不列为成功证据；成功证据是上述单行alembic current。只读终端标签已关闭，服务页保留。未读取数据库用户记录或环境变量密钥。

## 2026-09-16 发布前置核查

- GitHub已登录设置页确认：classic branch protection未配置，rulesets为空；页面提示当前私有仓库规则集需Team组织方案才执行。未改变仓库可见性、权限或订阅。
- Zeabur数据库service-6aa28aaea5990656aa82792e为postgres:18，1/1运行；自动备份关闭，备份历史页面未列记录，还原历史暂无记录。未触发备份/还原或付费扩容。
- 已向用户询问独立恢复测试及资源费用上限、专用更新签名密钥保管方案、OA具体测试项目。未确认前不作相关外部变更；不阻止独立本地开发。

本轮未提交、未推送、未部署，未创建新Release。

核实仓库：ZLZ1995/zq-report-review-system，private，main=d63628c68fbb895103fca1ef7d344145341660ad。
已有服务地址：https://zq-report-review.zeabur.app，实际当前构建待查。
历史Zeabur项目6a07c045d64413c4c61e54e6、服务6aa28a95a5990656aa82791a、环境6a07c045e5ed304c1d851182，须在控制台再次核实后操作。
浏览器现页DNS失败；不将页面URL中的部署ID当作当前运行证据。

发布前必填：分支保护/自动触发关系、数据库备份及恢复证据、签名来源、版本兼容矩阵、测试通过记录、最终提交和产物哈希。

## 本轮只读核实补充

- 重新打开Zeabur后访问恢复；已登录。项目untitled、目标服务及环境ID与上文一致。
- 服务1/1运行，显示Release 0.2.5发布说明；来源ZLZ1995/zq-report-review-system，main；监控路径为*。禁止直接向main试推送。
- 设置页有Dockerfile覆盖内容，仅复制现有服务端模块。未来共享契约/worker加入后须同步核对该覆盖，不能只修改仓库Dockerfile。
- 健康检查开关当前关闭；拟在G09验证后配置，不在本轮基线时改动。
- Windows httpx访问health返回200且status=ok；OpenAPI版本0.1.0。已部署路径未见skill-route与取消接口，不能假设本地0.2.6能力已上线。
- 数据库备份、迁移head和GitHub分支保护尚未核实；未读取环境变量明文。
