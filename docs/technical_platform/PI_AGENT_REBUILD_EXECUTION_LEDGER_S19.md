# S19 execution ledger: runtime recovery entry point

## Scope

- Reconcile durable open operations before a new gateway turn is admitted.
- Ensure a crashed process cannot leave the lane permanently busy.

## Red test

`test_gateway_recovers_open_operation_before_new_submit` created an accepted
operation, simulated process loss, and submitted a new message. Before the
fix the new submission returned `OperationBusy`/failed.

## Change

`AgentGateway.submit` now calls `AgentKernel.recover(session_id)` immediately
after creating the kernel and before `kernel.submit`. Recovery marks stale
operations/turns/tool calls as `unknown`, writes a visible error entry, and
emits recovery events. The current turn is then admitted normally.

## Verification

- Recovery regression: 1 passed.
- Gateway, recovery, and worker acceptance tests: **19 passed**.
- S17 session suite remains **102 passed** on D: temp.

## Gate

S19 recovery entry point is **passed**. Per-session UI worker queues and
cross-thread cancellation remain separate follow-up items in the runtime
lifecycle stage; they have not been claimed complete.

## Next action

Implement and test per-session/lane serialization and cancellation ownership,
then add approval timeout and shared long-lived model/token lifecycle.
