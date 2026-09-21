# PI Agent rebuild execution ledger — S42

Date: 2026-09-21

## Scope

Cut a schema-compatible local release candidate after confirming that the
online stable endpoint is still serving 0.2.10/data schema 11 while the local
pi-agent rebuild is schema 15. Reusing the 0.2.10 identity would make the
signed updater reject the candidate as a replay or incompatible downgrade.

## Changes

- `CLIENT_VERSION` advanced to `0.2.11`.
- `CLIENT_RELEASE_SEQUENCE` advanced to `6`.
- `UPDATER_VERSION` remains `0.2.10`.
- Release-panel regression now uses a strictly newer synthetic 0.2.12 record;
  the client must never offer the same-version release as an update.
- Release identity test now asserts the actual local schema `15`.

## Verification

- `tests/technical_platform/agent_rebuild tests/technical_platform/test_release_info.py tests/platform_update`:
  `518 passed, 9 xfailed` with `PYTHONPATH=src` and isolated `SystemDrive=Z:`.
- EXE build output: `dist/s42` (client, managed updater, launcher,
  `QtWebEngineProcess.exe`).
- Ordinary package:
  `dist/s42/ZQ-Workspace-0.2.11-Windows.zip`
  size `281866249`, SHA-256
  `1be8df482fec7472c4a1dacf93d37e3bb9bfa6378b3dc650fcc894607da39c51`.
- Managed transition package:
  `dist/s42/ZQ-Workspace-0.2.11-Managed-Windows.zip`
  size `421609569`, SHA-256
  `b6e32968c934ad777bda9747ac2be3cadfed571c8a06dc783765dd50b17e9ad1`.
- Signed manifest:
  `build/s42/release/manifest.json`, manifest SHA-256
  `44297ce7bf4f3c9b70ba8403919995f8fc01dea9418e21efe0c9ae871ee3275d`.
- Offline signature verification: passed with `D:/1/KEY`, key id
  `zq-release-20260917`, sequence `6`, schema range `[15,15]`.
- Managed manifest verification: passed; manifest SHA-256
  `30f1b2ffed51c04182586568a70a92fc18771a160854d77bffc3802400dbc157`.
- Release workflow asset set is locally complete: ordinary and managed ZIPs,
  plus their JSON manifests, are present under `dist/s42`.

## Online evidence and remaining gate

At `https://zq-report-review.zeabur.app/api/v1/capabilities` the service
returned HTTP 200 and build SHA
`eda21aec50ba68d70c1db06f624094ca3d14506e`, with all required capability
flags enabled. The current-release endpoint still returns version `0.2.10`,
sequence `5`, schema range `[11,11]`, and a different manifest/package hash.
Therefore this S42 candidate is verified locally but is **not published**:
GitHub upload, public release creation, and Zeabur activation require the
external release path to accept the new asset and must be performed only after
that path is available. No online state is claimed as updated here.
