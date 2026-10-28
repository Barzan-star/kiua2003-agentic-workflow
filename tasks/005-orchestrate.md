# Task 005: Orchestrate the checked workflow

## Goal
Implement the repository runner so it executes the existing probe and checks,
then generates and validates a summary with bounded retries. Preserve a useful
dry-run preview and keep run evidence in ignored `out/` paths.

## Scope
- Update `harness/run.sh` to support both existing options, `--offline` and
  `--dry-run`, including either option by itself or both together. Resolve the
  repository root from the runner's own location so execution works from any
  starting directory.
- In dry-run mode, print each planned stage, its inputs and outputs, and its
  checks. Do not execute a stage or checker, call Codex, make a network
  request, or write any files.
- In actual mode, create/use ignored `out/` evidence paths, run the probe
  (`python3 harness/probe.py`, adding `--offline` when requested), and then run
  `python3 eval/check_probe.py`. A probe or probe-check failure must stop the
  workflow before any model call.
- Generate each summary attempt with the verified command and settings in
  README: `timeout --kill-after=5s 90s codex exec --strict-config --ephemeral
  --json -m gpt-6-luna -c 'model_reasoning_effort="low"' -c
  'default_permissions="course_summary"' -c 'approval_policy="never"' -c
  'web_search="disabled"' -c 'agents.enabled=false'`. Keep using
  `harness/prompts/summarise.md` as the instruction input. Each attempt must
  write to a new candidate file under ignored `out/`; capture its Codex event
  output and stderr in attempt-specific log files there.
- Allow no more than three summary attempts. Run `eval/check_summary.py`
  against the current attempt's candidate and `out/probe.json`, using the
  checker's path arguments. Retry only when the checker exits with status 1
  (content rejected). Include the checker's complete feedback in the next
  attempt's prompt input, retaining the original summary instructions.
- Stop immediately and return nonzero on a Codex failure or timeout, or on a
  summary-checker file/input error (including checker exit codes other than
  0 and 1). Stop on the first passing summary. Only after a candidate passes,
  copy it to `out/summary.md`. If all three candidates are rejected, return
  nonzero and leave `out/summary.md` untouched.
- Never use an existing `out/summary.md` as an attempt candidate or as proof
  of success. Use distinct candidate and log names for every attempt and
  preserve existing run evidence rather than overwriting it.
- Add deterministic standard-library tests in `tests/test_workflow.py` using
  stubbed processes/commands. Cover stage ordering, dry-run behavior, stopping
  before the model on probe failure, checker feedback followed by success,
  three rejected attempts, process failure, and stale-output prevention.
  Tests must not call a real model or network.
- Update `README.md` to document the implemented orchestration, dry-run, retry
  behavior, and offline execution.
- Do not change `eval/check_probe.py`, `eval/check_summary.py`, the fixture,
  probe implementation, or permission profiles.

## Acceptance
- Running the workflow from outside the repository root locates all inputs,
  scripts, and outputs relative to the repository.
- Dry-run reports the complete plan without executing or writing anything.
- Probe and probe checker run before any Codex command, and failures stop
  execution before summary generation.
- Every summary check consumes the fresh candidate for that attempt. A prior
  `out/summary.md` cannot make a failed or missing candidate pass.
- Only checker exit status 1 triggers a retry, with the exact feedback
  included in the next model input. Codex errors/timeouts and checker input or
  file errors stop immediately. A passing candidate is published immediately;
  three rejections produce a nonzero result.
- Attempt candidates and logs are retained under ignored `out/` paths without
  replacing earlier evidence.
- Deterministic tests cover every case listed in Scope and make no model or
  network calls.
- The implementation changes only `harness/run.sh`, `tests/test_workflow.py`,
  and `README.md`; checkers, fixture, probe implementation, and permission
  profiles remain unchanged.

## Verification after implementation
After reviewing the implementation and deterministic tests, run the actual
workflow with `--offline`. Do not run live mode. Also run the project checks
from the repository root:

```sh
python3 harness/probe.py --offline && python3 eval/check_probe.py
python3 -m unittest discover -s tests
git diff --check
```

## Completed checkpoint — 2026-10-28

- The deterministic suite passed all 28 tests.
- The actual `./harness/run.sh --offline` execution exited 0 and passed on
  summary attempt 1.
- The published `out/summary.md` independently passed
  `eval/check_summary.py` with exit code 0. It correctly included the minimum
  -0.3 °C and maximum 16.6 °C.
- Run evidence: `out/workflow-20261028T065410Z-mTeyor`.
- No live MET request was made. Retry and failure paths were tested with
  stubs; the successful model run did not exercise those paths.
