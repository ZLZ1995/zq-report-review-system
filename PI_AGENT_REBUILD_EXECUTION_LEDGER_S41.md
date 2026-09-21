# PI Agent 重构执行账本 S41

## 发布施工工具修复

- `scripts/package_technical_platform.py` 新增独立 `source_root` 参数，并支持 `TP_PACKAGE_ROOT` / `TP_SOURCE_ROOT` 环境变量。
- 解决构建目录与源码目录分离时无法打包的问题；默认仓库内 `dist/technical_platform` 行为保持兼容。
- 重写打包测试夹具，使用稳定 Unicode 转义避免 Windows 中文代码页造成的测试路径失真。
- 为更新测试与 Agent resources 测试增加包边界并修正相对导入，消除同名 `test_manifest` 收集冲突。

## 真实候选包

- 普通包：`dist/s38/ZQ-Workspace-0.2.10-Windows.zip`
  - 大小：281,866,582 bytes
  - SHA256：`8928e80671c42c2e3dad07bf29786ef59325eee130350943709d461f636a9bce`
- 托管过渡包：`dist/s38/ZQ-Workspace-0.2.10-Managed-Windows.zip`
  - 大小：421,610,283 bytes
  - SHA256：`634752fdba6fc6c9aa2fb431f68e1297c765d788922e652ed8399ad24080e723`
- 签名清单：`build/s38/release/manifest.json`
  - key：`zq-release-20260917`
  - manifest SHA256：`86b86192fb78b115d8365c00c63718ccd8442128eb26655a4c336b5ad825b29c`
- `verify_client_release.py` 已返回 `verified_with_embedded_public_key`。

## 验收

- 更新链测试：105 passed。
- Agent rebuild + 更新链联合测试：505 passed, 9 xfailed，耗时 64.47s。

## 边界

- 签名和验签已完成，但没有上传 GitHub Release、激活云端渠道或修改 Zeabur；外部发布仍需在 GitHub/Zeabur 恢复可验证访问后执行。
- 该候选版本的 manifest 下载地址指向 GitHub Release v0.2.10，上传前必须确认 Release 资产名称与 SHA256 完全一致。
