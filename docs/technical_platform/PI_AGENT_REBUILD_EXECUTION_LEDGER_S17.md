# S17 execution ledger: session integrity repair

## Scope

- Goal: repair cross-session lane leaf corruption and make the migration repair existing databases.
- Repository: `D:\ZQ-Acceptance\pi-agent-rebuild`
- Branch: `kimi/pi-agent-core-rebuild`
- Baseline commit: `cc23575`
- No EXE, GitHub, Zeabur, or release changes were made.
- Existing dirty files and the untracked `NUL` file were preserved.

## Red test

Added `test_main_lane_leaf_is_scoped_by_session`.
Before the fix it failed because appending to session `s2/main` moved the
`s1/main` leaf, causing `s1` history to become empty.

## Changes

1. `sqlite_repository._insert_entry` now updates `agent_lanes` with both
   `session_id` and `id`.
2. Schema version increased from 14 to 15.
3. `apply_v15` rebuilds every lane leaf from the newest entry in its own
   `(session_id, lane_id)` partition and preserves the anchor for empty lanes.
4. Added `test_lane_leaf_repair_rebuilds_each_session_partition`.
5. Updated the fresh-database migration assertion to expect version 15.

## Verification

- Initial target session run on the default C: pytest temp path: 99 passed,
  3 failed. Two failures were blocked by the repository's non-system-drive
  migration safety policy and one was a stale v14 assertion.
- After moving the pytest base directory to D: and updating the migration
  assertions, the target session suite is green: 102 passed.
- The new regression and repair tests pass.

## Gate

S17 is **passed** for the approved non-system-drive test environment. The
C-drive migration refusal remains intentional and is recorded as a test
environment constraint; production data is not placed on C:.

## Next action

Prepare a non-system-drive migration test fixture (without weakening the
production C-drive protection), rerun the complete session suite, then begin
the single-source-of-truth/legacy migration stage.
