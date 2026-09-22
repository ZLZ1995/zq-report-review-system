# S20 execution ledger: skill registry tool wiring

## Scope

- Connect the gateway to the declarative Skill registry when a registry is
  supplied.
- Expose registered Skill tools through the same active tool catalog used by
  the Agent model.
- Preserve existing business and browser tool gating.

## Change

`AgentGateway` now accepts an optional `tool_registry`. When a Skill category
is enabled, its resolved tools are included in `active_tools()`. This removes
the previous hard dependency on the legacy `business_tools` list for Skill
tool discovery and gives the model/UI one path to the installed Skill catalog.

## Verification

- Added a temporary manifest/executor integration test proving a registered
  `demo_lookup` tool is visible through `AgentGateway.active_tools()`.
- Full `tests/technical_platform/agent_rebuild`: **382 passed, 9 xfailed**.
- No template, business source document, EXE, GitHub, Zeabur, or release was
  changed.

## Gate

S20 is **passed** for registry discovery. Full production construction of the
registry (user/project roots, executor injection, pinned snapshots and file
content readers) remains in the next stage; this stage does not claim those
items complete.

## Next action

Add scoped file-content/preview tools and wire a composite resolver so every
operation persists Skill version/hash plus the exact file scope used for the
model context.
