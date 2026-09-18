# ADR 0007：权限模式与硬拒绝规则

- 状态：已接受（三档模式已实现；PermissionDecision 统一化随 G06–G08 落地）
- 日期：2026-09-18

## 背景

三档权限模式已实现（`agent_permission_modes.py`）：`request`（请求批准）/ `risk`（帮我批准，默认）/ `full`（完全访问权限），覆盖联网、生成、Skill 安装、软件更新、浏览器动作/上传/下载；切换模式停止活动任务并撤销浏览器租约。模式只决定"何时询问"。当前决策散落在 `app.agent_operation_allowed`、`browser_action_prompt`、`browser_window` 等处，返回布尔值，没有统一的决策对象携带理由与租约。

## 决定

1. 保留三档模式，引入统一 `PermissionDecision`：mode、action、resource、scope、risk_level、policy_rule、decision（allow/ask/deny）、reason、lease_id/expires_at/single_use。
2. 模式只提供默认决策；具体动作仍经规则解释并保留拒绝历史。
3. 硬性 deny 不被"完全访问权限"覆盖：修改原始业务文件；上传 hidden/veryHidden 内容；客户端读取供应商 API Key；未选历史附件进入任务；外部 Skill 执行未登记脚本；跨项目/账号/origin 复用旧授权；在系统盘默认创建业务资料与成果。
4. 浏览器动作回执维持一次性、60 秒、先消费后派发（`permissions.py` 现有语义），决策对象只增加可解释性，不放宽约束。

## 替代方案

- 模式即全部授权语义：拒绝，红线必须独立于用户偏好。
- 每模块各自实现决策对象：拒绝，解释与审计需要统一载体。

## 后果

- `agent_permission_modes.py` 的布尔判定逐步包进 PermissionDecision；UI 确认对话框显示动作、对象、风险、依据。
- 权限模式持久化沿用 `storage_preferences.account_settings` 按账号存储。
- 测试需证明：full 模式下硬拒绝项仍然拒绝。

## 验收

- 三档切换语义回归（现有 test_agent_permission_modes 等）保持通过。
- 新增：每个 allow/ask/deny 决策可给出 policy_rule 与 reason；硬拒绝项在 full 模式下的负测通过。
