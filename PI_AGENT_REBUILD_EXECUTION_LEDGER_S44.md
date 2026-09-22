# PI Agent 重构执行账本 S44

## 目标

将已验证的 Pi Agent 重构改动与最新 GitHub `main` 集成，并继续客户端、服务端及在线更新链路验收。

## GitHub 集成

- 最新 `origin/main` 基线：`18e73f40`，含服务端流式接口、refresh-token 迁移及部署探活相关提交。
- 集成分支：`kimi/pi-agent-core-rebuild-integrated`。
- 代码集成提交：`46957c37b355149c1dbb8d58282e3ff2eee6a140`。
- 最新 PR 更新提交：`4518251b7afc660168f09de77402bec807d2e41d`。
- PR：[#1 Integrate Pi agent rebuild onto latest main](https://github.com/ZLZ1995/zq-report-review-system/pull/1)。
- PR 与 `main` 无冲突；创建时 2 个 GitHub Actions 检查正在运行，当前未合并、未发布。

## 本地验证

- 集成后的聚焦回归：65 passed（pytest 临时目录位于非系统盘）。
- 全量回归：2394 passed、1 skipped、9 xfailed、2 failed；另有 3 个根目录测试因引用仓库中不存在的 helper 而无法收集，故排除。
- 两个失败均为诊断日志断言，单独合并运行时 2 passed；全量顺序下失败原因尚未定位，因此完整本地回归门槛仍未通过。
- 集成差异检查通过。原有未跟踪 `NUL` 文件保留，未触碰。

## 当前结论与下一步

1. 等待 PR CI 检查结果，同时定位全量测试中两个日志测试的顺序相关失败。
2. 全量回归与 PR 检查通过后再合并；从最终合并提交重建、签名并验证客户端。
3. 再核对 GitHub Release 资产、Zeabur 当前版本与 Build SHA，并完成在线更新探活。
4. 本轮没有激活稳定发布；不得把既有 S43 候选包当作集成提交的最终包。

## 2026-09-22 续行检查点

- GitHub 最新 PR 分支提交：`f2e1709d265251c805e3a03f90f412a0d804a664`（`portable-tempdir-tests`）。此前 `client-regression` 的 27 项失败由 5 个测试文件硬编码 `D:\ZQ-Acceptance\tmp-pytest-basetemp` 引起，在 GitHub Runner 上该目录不存在；已改为系统临时目录。
- 修复回归：相关 5 个测试模块 `32 passed`；与 GitHub Actions 同范围的客户端回归 `tests/platform_update tests/technical_platform tests/report_review_app` 全量通过：`2150 passed, 9 xfailed`（本机 15m37s）。
- GitHub Actions（PR #1，提交 `f2e1709`）：`server-tests`、`server-image`、`client-regression`、`client-build` 均成功；Windows 候选包已由 CI 构建并上传为 workflow artifact，尚未签名或发布。
- Zeabur 只读探活：`/api/v1/health` 返回 HTTP 200；`/api/v1/client-releases/current` 返回 HTTP 200，当前稳定版仍为 `0.2.10`、sequence 5、schema 11。当前 PR 尚未合并，因此这些结果不代表新接口已部署。
- 推送 `f2e1709` 时 GitHub 曾短暂返回 `fatal error in commit_refs`；重试成功，远端分支已核对到同一 SHA。
- 工作区的未跟踪 `NUL` 文件继续保留；`dist/s44` 既有 `0.2.11` 候选资产及元数据未改动，不能认作由 `f2e1709` 构建。

### 后续门禁

1. 将本次检查点提交并推送后，核对新触发的 PR checks；代码回归已有本地与 GitHub 通过证据。
2. 全部检查通过后合并 PR，使 Zeabur 自动部署 main；核对实际部署 SHA 与接口/能力探活结果。
3. 从最终 main 合并 SHA 构建正式客户端，核对 ZIP/EXE 哈希、清单、客户端版本与 schema；用 `D:\1\KEY` 中的发布私钥按既定流程签名。不得覆盖或复用 `dist/s44` 旧候选。
4. 先验证更新清单、签名、下载和客户端兼容性，再发布/激活稳定通道；完成升级探活后才结项。
