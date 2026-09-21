# PI Agent Rebuild Execution Ledger — S44

## Scope

本轮修复全量回归中暴露的本地迁移兼容性、UI 提交门控和 stage-1 兼容适配问题。生产客户端仍保持“真实登录客户端只走新 Agent”边界；兼容路径仅服务于离线预览、确定性测试适配器和未登录的本地测试客户端。

## Findings and changes

1. `local_migrations.apply_v15` 对不存在的 `agent_lanes` / `conversation_entries` 表直接查询，导致旧数据库在升级到 v15 时启动失败。现在迁移先检查表存在性，缺少车道表时将 v15 作为 repair-only no-op。
2. `PlatformWindow.submit` 在新 Agent 切换后缺少统一 TurnEnvelope 入口，导致未连接场景无法先完成文件范围校验，`last_turn_envelope` 也为空。现在每个普通提交先经 `InputGateway.create/verify`，失败时保留输入并显示明确范围错误。
3. 新 Agent-only 门控把所有无令牌适配器和离线本地路径提前拦截。现在仅对非 `RemoteSessionClient` 且显式暴露 `understand_task` 的适配器启用 stage-1 兼容 worker；真实 `RemoteSessionClient` 仍只构造新 Agent gateway。
4. stage-1 兼容 worker 现在读取已启用、依赖完整的外部 Skill manifest，使外部 Skill 能参与自然语言路由；不执行 ZIP 内脚本。
5. 本地内置路由补齐“评估明细表”及“评估明细表 + 财务简报”的复合识别；注入 Agent gateway 的测试/生产路径不被本地快捷路由截获。

## Verification

- `tests/technical_platform/agent_rebuild`: **400 passed, 9 xfailed**。
- 自动路由、浏览器任务（6 参数）、复合外部 Skill、复合窗口、本地生成链、离线/TurnEnvelope、v15 迁移及 Agent 文件范围专项：全部通过；专项组合结果 **至少 27 + 6 + 51 + 20 + 3 = 107 passed**（其中 agent_rebuild 已包含部分重叠测试）。
- `tests/technical_platform/test_local_migrations.py`: **20 passed**。
- `tests/technical_platform/test_browser_window.py`: **6 passed**。
- `tests/technical_platform/test_turn_context.py tests/technical_platform/test_offline.py`: **51 passed**。
- 针对性回归未发现本轮新增失败；未将被中断的长时间全量运行误报为全绿。

## Remaining external blockers

- GitHub 写入仍受当前环境网络/凭据限制，不能虚报推送。
- Zeabur 当前在线 release 仍是 0.2.10/schema 11；本地新构建需在服务端接口和 GitHub 写入恢复后再发布。
- 本轮代码变更尚未覆盖已发布 EXE；下一步应执行 S44 构建、签名、离线 manifest 校验，再按外部授权发布。

## Commit intent

本账本与代码应作为同一 S44 提交，保留既有未跟踪 `NUL` 文件，不纳入提交。
