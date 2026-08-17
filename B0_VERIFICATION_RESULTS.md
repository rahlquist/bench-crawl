# B0 Failure & Recovery Verification — Results

Task: t_efb897b9  (adversarial verify B0 failure and recovery behavior)
Reviewer/worker: @critic
Date: 2026-08-16
Suite: bench-suite @ /home/rahlquist/bench-suite  (commit before fix: a2a281a)

## Method
- Read full integration commit (a2a281a) and parent design tasks (t_b07be0ba, t_68338118, t_10101df9, t_58e5f9ff, t_5778f902).
- Built an adversarial harness (verify_b0.py) exercising state machine, dependency gating, cancellation, recover, snapshot roundtrip, and SerialWorkflow.run_all including a cancel-during-run race.
- Built a process-group orphan repro (repro_orphan.py) against the REAL adapters.base.run_cmd.
- Added pytest regression suite under tests/ (test_b0_acceptance.py, test_b0_integration.py).
- Ran full suite + compileall + git diff --check.

## Defects found

D1 [BLOCKING] B0 module is DEAD CODE — never wired into the live run path.
    execution.py / execution_contract.py (SerialWorkflow, SnapshotStore,
    DependencyScheduler, request_cancel, recover, make_run) are referenced only
    by each other. cli.cmd_run -> core.run_benchmarks -> run_one uses a plain
    subprocess.run loop. The "integrated" parent task t_5778f902 was marked
    done but the recovery/cancel/dependency state machine does NOT execute.
    Reproduction: grep shows SerialWorkflow/ SnapshotStore/ recover absent from
    cli.py and core.py. Test test_b0_integration.py::test_b0_workflow_is_not_used_by_live_run_path pins this.

D2 [HIGH] request_cancel was NOT idempotent.
    Second call returned True and re-transitioned state. Fixed: returns False if
    cancel_requested already set. Test test_request_cancel_is_idempotent.

D3 [HIGH] Orphaned subprocess on timeout (live path).
    run_cmd used subprocess.run WITHOUT start_new_session; on TimeoutExpired only
    the direct child was killed, grandchildren survived. REPRODUCED: grandchild
    PID survived a 1.5s timeout. Fixed: launch in own process group, killpg on
    timeout. Repro now shows grandchild reaped. Test test_run_cmd_kills_process_group_on_timeout.

D4 [HIGH] No 40-minute timeout boundary existed anywhere.
    Contract claimed one; integrated code had none. cfg.timeout_s defaults to
    7200 (2h) with no cap. Fixed: added MAX_BENCHMARK_TIMEOUT_S=2400 and
    clamp_timeout(); enforced in core.run_one (oversize requests are capped and
    surfaced to stderr). Test test_clamp_timeout_caps_at_40_min + integration test.

D5 [HIGH] SerialWorkflow.run_all contract mismatch with live AdapterResult.
    It read result.state / result.failure_reason, but AdapterResult uses
    status ('ok' for success) / error. If ever wired, every live success would
    map to FAILED (BenchmarkState('ok') raises, caught -> FAILED). Fixed: map
    AdapterResult.status vocabulary via BENCHMARK_STATE_FROM_ADAPTER_STATUS.
    Tests test_run_all_maps_live_result_status / _failure / _not_run_to_skipped.

D6 [MEDIUM] State machine blocked RUNNING -> SKIPPED.
    A 'not_run' adapter result maps to SKIPPED but the transition was disallowed,
    raising ValueError. Fixed: allowed RUNNING -> SKIPPED.

## Fixes applied (committed)
- benchsuite/execution_contract.py: idempotent request_cancel; added
  BENCHMARK_TIMEOUT_S / MAX_BENCHMARK_TIMEOUT_S / clamp_timeout; allow
  RUNNING->SKIPPED.
- benchsuite/adapters/base.py: run_cmd uses Popen + start_new_session, killpg on
  timeout (no orphaned grandchildren).
- benchsuite/core.py: enforce 40-minute clamp in run_one; report override to stderr.
- benchsuite/execution.py: map live AdapterResult.status/error to BenchmarkState.

## Test results
All 22 tests pass (test_b0_acceptance.py: 19, test_b0_integration.py: 3) plus
pre-existing tests/. compileall clean. git diff --check clean.

## Remaining / out-of-scope
- D1 (integration gap) is DOCUMENTED and pinned by a test, but NOT wired. Fully
  routing cli.cmd_run -> SerialWorkflow + SnapshotStore + recover is an
  architectural change to the live run path and should be a follow-up task, not a
  speculative rewrite during verification. The recovery/cancel/dependency logic
  is now correct in isolation and will be safe to wire.
- No SIGKILL-during-run cancel: cancellation is cooperative (flag checked between
  benchmarks). An in-flight benchmark cannot be interrupted mid-run; this matches
  the synchronous design and is documented in test docstrings.
