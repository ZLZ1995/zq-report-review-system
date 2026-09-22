# PI Agent rebuild execution ledger — S43

Date: 2026-09-21

## CI failure diagnosis and fix

The public GitHub Actions run `35588475352` for `technical-platform-client`
failed in `client-regression` at the static/security step. The job metadata
identifies the exact failing stage; the local equivalent reproduced
`ruff ISC004` at `scripts/build_technical_platform.py:51` (implicit string
concatenation inside the hidden-import argument list). The build job was
skipped because regression failed. This was a build/harness lint defect, not
an Agent runtime or model-protocol failure.

The hidden-import list was rewritten with an explicit parenthesized string and
trailing commas. No runtime behavior or release identity changed.

## Verification

- Exact CI ruff target list: `All checks passed!`.
- Agent/platform regression after the patch: `518 passed, 9 xfailed`.
- Rebuilt EXE tree: `dist/s43`.
- Ordinary package:
  `dist/s43/ZQ-Workspace-0.2.11-Windows.zip`
  size `281866826`, SHA-256
  `7264568954d4b3ba65f7c335519c909297bd6c5162de3e479a318a405ecf3126`.
- Managed package:
  `dist/s43/ZQ-Workspace-0.2.11-Managed-Windows.zip`
  size `421608852`, SHA-256
  `66fb5b48f97e9437e52e41416ad9291f0f73083d43d43496de128ecbb08a7bef`.
- Ordinary manifest SHA-256:
  `444b670e3552017dc24bf368a20370f309107037cb77fcc8704e9b0532c73d04`.
- Managed manifest SHA-256:
  `c25782ec298bc19410706dd2c4345cbe7f7174df00b96d6ac476f2d3652add1e`.
- Both manifests verified offline with `D:/1/KEY`, key id
  `zq-release-20260917`, sequence `6`, schema range `[15,15]`.

## Online release state

GitHub API read access is healthy and confirms only public stable releases
through `v0.2.10`; the web/Git transport path returns HTTP 400 in this
environment. No `v0.2.11` release or upload was created. Zeabur still serves
0.2.10/schema 11, so the S43 artifacts remain local signed candidates and
are not represented as active online releases.
