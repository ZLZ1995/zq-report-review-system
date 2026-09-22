# S18 execution ledger: turn attribution and model protocol

## Scope

- Prevent stale assistant text from being reused after a failed turn.
- Give every model turn a unique idempotency request id.
- Send the active tool descriptors to the model provider.
- No EXE, GitHub, Zeabur, or release changes.

## Red tests

1. `test_failed_turn_does_not_reuse_previous_assistant_reply` failed because
   the gateway searched all assistant entries in the session.
2. `test_each_model_turn_has_a_distinct_idempotency_request_id` failed because
   all turns reused the operation request id.
3. `test_single_tool_call_round_trip` failed because `ModelRequest.tools` was
   empty even when the kernel had registered tools.

## Changes

- `AgentGateway._last_assistant_text` now filters by the current operation id;
  a failed turn therefore returns an empty reply and the UI creates only its
  current error message.
- `run_agent_loop` derives `operation_request_id:turn:N` for every model turn.
- `run_agent_loop` copies each active tool's descriptor into `ModelRequest`.

## Verification

- Target gateway/UI tests: 26 passed.
- Target model protocol tests: 2 passed.
- Full `tests/technical_platform/agent_rebuild`: **380 passed, 9 xfailed**.
- S17 session suite on D: non-system temp: **102 passed**.

## Gate

S18 is **passed**. The remaining xfails are pre-existing characterization
defects explicitly tracked for later stages; no assertion was weakened.

## Next action

Start S19 runtime lifecycle: per-session serialization, startup recovery,
thread-safe cancellation, approval timeout, and shared model-token lifecycle.
