# PI Agent Rebuild Execution Ledger — S44

## Scope

本轮修复全量回归中暴露的本地迁移兼容性、UI 提交门控和 stage-1 兼容适配问题。生产客户端仍保持“真实登录客户端只走新 Agent”边界；兼容路径仅服务于离线预览、确定性测试适配器和未登录的本地测试客户端。

## Findings and changes

1. `local_migrations.apply_v15` 对不存在的 `agent_lanes` / `conversation_entries` 表直接查询，导致旧数据库在升级到 v15 时启动失败。现在迁移先检查表存在性，缺少车道表时将 v15 作为 repair-only no-op。
2. `PlatformWindow.submit` 在新 Agent 切换后缺少统一 TurnEnvelope 入口，导致未连接场景无法先完成文件范围校验，`last_turn_envelope` 也为空。现在每个普通提交先经 `InputGateway.create/verify`，失败时保留输入并显示明确范围错误。
3. 新 Agent-only 门控把所有无令牌适配器和离线本地路径提前拦截。现在仅对非 `RemoteSessionClient` 且显式暴露 `understand_task` 的适配器启用 stage-1 兼容 worker；真实 `RemoteSessionClient` 仍只构造新 Agent gateway。
4. stage-1 兼容 worker 现在读取已启用、依赖完整的外部 Skill manifest，使外部 Skill 能参与自然语言路由；不执行 ZIP 内脚本。
5. 本地内置路由补齐“评估明细表”及“评估明细表 + 财务简报”的复合识别；注入 Agent gateway 的测试/生产路径不被本地快捷路由截获。
6. 修复 stage-1 兼容适配器遗漏权限门禁的问题：请求批准模式下用户拒绝后不再清空输入或启动模型调用；该路径现在与新 Agent 的 `network` 操作门禁保持一致。

## Verification

- `tests/technical_platform/agent_rebuild`: **400 passed, 9 xfailed**。
- 自动路由、浏览器任务（6 参数）、复合外部 Skill、复合窗口、本地生成链、离线/TurnEnvelope、v15 迁移及 Agent 文件范围专项：全部通过；专项组合结果 **至少 27 + 6 + 51 + 20 + 3 = 107 passed**（其中 agent_rebuild 已包含部分重叠测试）。
- `tests/technical_platform/test_local_migrations.py`: **20 passed**。
- `tests/technical_platform/test_browser_window.py`: **6 passed**。
- `tests/technical_platform/test_turn_context.py tests/technical_platform/test_offline.py`: **51 passed**。
- 最终针对性回归（`SystemDrive=D:`，避免将测试临时目录误判为业务系统盘）：**510 passed, 9 xfailed**；其中权限模式专项已验证拒绝后 `calls=[]` 且输入保留。
- 此前一次未设置 `SystemDrive=D:` 的本地回归出现 31 个环境策略误报（测试临时目录位于 `C:` 被业务目录保护拒绝），不计入代码验收；已用正确环境变量重跑并通过。
- S44 EXE 已构建并通过打包健康探活：`client=0.2.11`、`schema=15`、登录窗口可见、WebEngine 导入通过。
- 普通候选包：`dist/s44/ZQ-Workspace-0.2.11-Windows.zip`，281,868,183 bytes，SHA256 `f01cd6d7984d6bebae3366690d9abf327541ac3bf91227277f2219f8fd65ed81`。
- 托管更新候选包：`dist/s44/ZQ-Workspace-0.2.11-Managed-Windows.zip`，421,611,052 bytes，SHA256 `d55d2330245a1b01a1c1f7ef2f57235c1e89c7af6885caf23df8ca48e29b8e71`。
- 两个 manifest 均使用 `zq-release-20260917`、sequence 6、schema [15,15]，并通过内置公钥离线验签；manifest SHA 分别为 `5702f640503b07ad348843ea10d24a21ecd2ce5a0d4e3786a0d21721c482f0f6`、`3d126c67ad121937ac993ba8b7e2b23b7ad352241c6ab79b659e2b04cad13c10`。

## Remaining external blockers

- GitHub 写入仍受当前环境网络/凭据限制，不能虚报推送。
- Zeabur 当前在线 release 仍是 0.2.10/schema 11；本地新构建需在服务端接口和 GitHub 写入恢复后再发布。
- 本轮代码变更已包含在 S44 候选 EXE、签名包和离线验签结果中；仍未覆盖线上已发布版本，需待外部发布权限恢复后再部署。

## Current external audit (2026-09-22)

- 在线能力探活仍为 HTTP 200，服务端 build SHA `eda21aec50ba68d70c1db06f624094ca3d14506e`，全部声明能力保持可用。
- `GET /api/v1/client-releases/current` 仍返回稳定版 `0.2.10`、sequence `5`、schema `11`；S45 `0.2.11` 尚未进入线上发布表。
- GitHub REST API 仅读探测成功（HTTP 200）；当前 Git remote 写入仍返回 HTTP 400，环境中没有可用 GitHub 写凭据，浏览器发布页也返回 GitHub Bad Request，因此不能安全执行推送或创建 Release。
- 本地总控发布/版本相关回归在业务盘环境变量下通过：`24 passed`（`tests/report_review_server/test_client_releases.py`、版本导出/版本信息/基线测试）；说明 S45 清单格式、签名校验和发布状态机在本地服务端逻辑中可接受。

## S45 post-fix candidate

为纳入本轮权限门禁修复，重新构建了同一 `0.2.11`/sequence 6 的候选包（不改变线上发布身份）：

- 普通包：`dist/s45/ZQ-Workspace-0.2.11-Windows.zip`，281,867,544 bytes，SHA256 `56af8971b6b943eb39f27cc937ca1a65436f32b6dd534aa6a20c6d86b2b3e8da`。
- 托管包：`dist/s45/ZQ-Workspace-0.2.11-Managed-Windows.zip`，421,612,219 bytes，SHA256 `f4319f73de77884377c604c797c7a0894a7669d3ea1a1748de17d80eee94dd71`。
- 普通 manifest SHA256 `aa41ac7558c7632f3b774245fa81f4f15c596c54a27131864b209a37baa202b4`；托管 manifest SHA256 `858180361088293b72d5328c01dd4ee4915bab021d1501740b969b0fac69920c`。
- 两个 manifest 均已离线验签通过，版本 `0.2.11`、sequence `6`、schema `[15,15]`、key id `zq-release-20260917`；新候选 EXE 健康探活通过。
- 全量技术平台回归主体：`1804 passed, 9 xfailed`。另将验收运行器按其各自安全边界分环境复核：系统盘检查组 `4 passed`（`SystemDrive=C:`），显式临时目录/子进程输出组 `2 passed`（`SystemDrive=Z:`）。全量过程中的 4 个失败仅因把 `SystemDrive` 设为工作区所在 D 盘而触发验收脚本的预期拒绝，不属于代码回归；按脚本设计环境拆分后验收运行器 6 项全部通过。

## Commit intent

本账本与代码应作为同一提交，保留既有未跟踪 `NUL` 文件，不纳入提交。
