# S45 发布交接单

## 当前候选

本地候选版本仍使用客户端版本 `0.2.11`、发布序号 `6`，已完成构建、签名、离线验签和 EXE 探活。

| 资产 | 路径 | SHA256 |
|---|---|---|
| 普通客户端 | `dist/s45/ZQ-Workspace-0.2.11-Windows.zip` | `56af8971b6b943eb39f27cc937ca1a65436f32b6dd534aa6a20c6d86b2b3e8da` |
| 托管客户端 | `dist/s45/ZQ-Workspace-0.2.11-Managed-Windows.zip` | `f4319f73de77884377c604c797c7a0894a7669d3ea1a1748de17d80eee94dd71` |
| 普通清单 | `dist/s45/release-manifest.json` | `aa41ac7558c7632f3b774245fa81f4f15c596c54a27131864b209a37baa202b4` |
| 托管清单 | `dist/s45/managed-release-manifest.json` | `858180361088293b72d5328c01dd4ee4915bab021d1501740b969b0fac69920c` |

## GitHub 发布顺序

1. 将源代码分支 `kimi/pi-agent-core-rebuild` 合入目标发布分支。
2. 创建公开 Release tag `v0.2.11`，目标提交必须是包含 S45 修复的提交 `ce93726` 及其父提交链。
3. 上传两个 ZIP；将 `release-manifest.json` 和 `managed-release-manifest.json` 作为对应清单资产上传。若总控约定资产名不同，只允许改名，不得修改 JSON 内容。
4. Release 下载地址必须与清单 payload 中的 URL 完全一致；上传后重新用 `scripts/verify_client_release.py` 校验。

## Zeabur 总控顺序

1. 登录 `/admin#client-releases`。
2. 粘贴普通 `release-manifest.json` 的完整内容，创建发布草稿。
3. 先切换灰度，使用客户端探活确认下载、验签、候选健康检查和回滚保护。
4. 灰度通过后再激活稳定；确认旧稳定版本自动撤回。
5. `GET /api/v1/client-releases/current` 必须返回 `version=0.2.11`、`sequence=6`、`data_schema_min/max=15`，并且 `manifest_sha256` 为 `aa41ac7558c7632f3b774245fa81f4f15c596c54a27131864b209a37baa202b4`。

## 当前阻塞

截至 2026-09-22，GitHub REST API 只读正常，但 Git remote 写入仍 HTTP 400，环境没有可用 GitHub 写凭据；Zeabur 当前稳定版仍为 `0.2.10/sequence 5/schema 11`。恢复 GitHub 写权限或由管理员在总控完成以上操作后，继续做线上验收，不得提前宣称发布完成。

