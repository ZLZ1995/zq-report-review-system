# S22 execution ledger: atomic file binding and scope snapshot

## Scope

- Reject malformed file bindings before accepting a durable operation.
- Persist the exact file ids, hashes and binding kinds used by the operation.

## Changes

- `AgentKernel.submit` validates the entire binding batch before
  `begin_operation`; malformed input no longer leaves a running operation or
  user entry behind.
- SQLite and in-memory repositories now persist a file-scope snapshot after
  bindings are attached.

## Verification

- Invalid-binding regression: passed.
- SQLite scope-snapshot persistence regression: passed.
- Full `tests/technical_platform/agent_rebuild`: **385 passed, 9 xfailed**.

## Gate

S22 is **passed**. The snapshot is now durable, but production gateway
construction still needs to provide a concrete path-based `FileScope` and a
composite pinned Skill resolver; that is the next stage.

## Next action

Wire the composite resolver and real browser backend, then verify permission
decisions use the accepted scope rather than an empty default.
