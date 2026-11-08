# Task 014 Phase C1 budget integration record

Date: 2026-11-08

Scope: connect the existing budgeted Responses adapter to normal course runs

Status: implemented and checked offline; actual evaluation remains disabled

## Integration decisions

- `harness/course_workflow.py` is the shared extraction, checker, retry, and
  render entry point. Its caller supplies one existing `TokenLedger`, an
  injected SDK client, a source bundle, and a new case evidence directory.
  The controller neither constructs nor resumes a ledger. This lets a future
  batch evaluator pass the same ledger to successive case invocations.
- The source bundle is validated with the existing request builder before a
  provider call. The controller works from a detached snapshot and leaves
  source metadata and section text intact. The existing adapter remains the
  only implementation of request construction, input counting, reservation,
  generation, usage validation, and settlement.
- Execution is serial. Only a completed checker exit code 1 can trigger a
  retry, with the exact candidate JSON and complete stdout/stderr feedback
  passed through the existing repair-input contract. A malformed repair
  candidate is recorded as a protocol failure and stops the run. There are at
  most three candidate attempts per case.
- Candidate files, per-attempt checker output, hashes, request provenance,
  budget snapshots, and rendered files stay under the run evidence tree. The
  stable `candidate.json` points to the most recent completed candidate even
  after rejection. The controller itself never writes the two normal
  publication files.
- Collector, checker, and renderer subprocesses run with `OPENAI_API_KEY`
  removed. Provider diagnostics do not copy exception strings or native SDK
  objects. The normal CLI checks for a nonempty runtime key without printing
  it, validates all three explicit positive integer limits before creating
  output, and creates the native SDK client only for an actual run. It closes
  that client after the controller returns.
- `--offline` selects the checked-in source fixture only; model extraction
  still uses the service. Dry-run reports collection, count/generation,
  checker, render, limits, and evidence locations without a key, SDK, budget
  values, source collection, subprocess execution, client construction, or
  file creation.
- The CLI publishes only after checker acceptance and successful rendering.
  It stages both local output contents before replacing either destination,
  then replaces JSON and Markdown in separate operations. The pair is not
  represented as an atomic transaction.
- The wrapper resolves the repository root from its own location and selects
  `.venv/bin/python` when executable, otherwise `python3`. Invocation from
  outside the repository is retained.

## Verified provider checkpoint

The source evidence remains under
`out/exam/task-014/live-20261108T083934Z-72p24bam/`. The recorded receipt,
usage, ledger, count, plan, calls, candidate, checker result, and source were
read for this integration. The checkpoint reports:

- `gpt-6-luna`, runtime reasoning `low`, OpenAI SDK 3.46.0, and zero SDK
  retries.
- Initial counted input and completed-response input usage both 4,414 tokens.
  Output usage was 1,801 tokens, including 163 reasoning tokens; total usage
  was 6,215 tokens.
- The configured output cap was 12,000 tokens, the run limit was 16,414, and
  10,199 tokens remained after settlement. Two input-count requests covered
  planning and execution, with exactly one generation request.
- The ledger refused a further request before either provider endpoint was
  touched, although one of the two model-call slots remained. The candidate
  checker passed, protected files were unchanged, and the probe exited 0.
- Count and create shared payload SHA-256
  `a40cb8bf09448efa6193724efe81abe8b19e287433cf78bfae95f9f9ceacddb7`.

This is one observed count/usage agreement and one pre-dispatch budget
refusal. The provider output cap was supplied and usage remained below it;
the run did not intentionally exhaust that cap. This is not a dollar spending
guarantee, a production-integration result, or a nine-case evaluation.

## Independent pilot score

The unchanged checkpoint candidate was scored offline against the reviewed
`S00-base` reference with
`course_evaluation_scoring.score_candidate(..., provenance="recorded_model")`.
The recomputed report is saved separately at
`out/exam/task-014/live-20261108T083934Z-72p24bam/independent-pilot-score.json`.

- Value slots: 20 correct of 21; no missing slots and one incorrect slot.
- Required text atoms: 17 of 17 covered.
- Prerequisite atoms: 11 of 11 covered.
- The only incorrect slot is `robot-delivery-format`: the candidate provides
  a supported delivery format and also lists that field as missing.

This is one recorded pilot, not overall model accuracy. The candidate,
checker, prompt, and benchmark were not changed or repaired. Qualitative
review of the complete evaluation set remains pending.

## Initial offline verification and limits

The Phase C1 verification is limited to the two focused workflow suites,
wrapper syntax and dry-runs, fixed-corpus validation, offline evaluation
replay, and whitespace checking. These checks use test-local SDK doubles and
offline inputs; they do not make live provider requests. The complete
SDK/MCP-enabled repository suite remains for ordinary WSL after review.

No normal paid run or actual evaluation was performed for this integration.
`harness/evaluate_courses.py --actual` remains disabled and unchanged. There
are no workers, delegated jobs, background calls, second evaluation retry
loop, Codex fallback, or implicit numerical budget choices. The complete
qualitative evaluation, actual evaluation wiring, and any further provider
validation remain later work.

## Failure-containment review

The initial passing suites did not exercise every infrastructure boundary.
Injected snapshot/provenance/result write failures, lost renderer evidence,
and checker/renderer interruption exposed unsafe continuations. In
particular, the controller could report acceptance despite a lost render
receipt or permit another case after a failed/interrupted component.

The expanded controller suite ran 20 tests against the initial implementation
and recorded 5 failures and 3 errors. The repair blocks the caller's existing
ledger before returning an infrastructure abort, attempts final error and
budget receipts independently, and never converts logging failure into
permission to continue. Source validation uses the existing contract
separately from prompt/schema and snapshot storage. Missing renderer evidence
is fatal. The normal CLI sanitizes unexpected errors and returns 130 for
interruption. Existing accepted-source data and model-call accounting were
not weakened.

All 20 repaired controller tests and 12 CLI tests passed. The broader
SDK-independent run passed 211 tests with zero skips, explicitly excluding
the MCP and native SDK test modules unavailable in that environment.
Additional CLI coverage verifies collection failure/staleness, provider
timeout/empty output, token exhaustion, rendering failure, preserved older
publication, and root resolution. Full SDK/MCP verification in ordinary WSL
is still pending. These are controlled offline failures and repairs; no
additional provider request, live collection or actual evaluation was run.

## Completed ordinary-WSL checkpoint

The completed verification evidence is preserved under
`out/exam/task-014/wsl-c1-review-2n94oqjf/`. All 230 tests passed with no
skips; all 11 recorded commands exited 0; and all 20 preserved-file hashes
matched. The eight-path scope, protected-file, runner mode 100755, and
`compulsory2-skeleton` tag checks passed. Earlier verification results above
remain historical records, not replacements for this completed checkpoint.

Actual evaluation and a live normal-workflow run remain pending.
