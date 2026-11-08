# Course-model evaluation interface — 2026-11-08

The fixed evaluation cases now use the shared budgeted course controller.
This work covered integration, deterministic verification and failure
containment for a complete evaluation invocation.

## Scope

Task 014 Phase C2 connects the fixed Task 013 evaluation inputs to the existing
Task 014 C1 shared controller. The implementation changes the evaluation
runner and scoring boundary, adds deterministic injected-client tests, and
updates the project/task documentation. The case generator, controller,
ledger, adapter, production checker, renderer, collector, prompts, schema,
requirements, fixtures, references, CI, permission profiles, W43 material,
and existing tests remain unchanged.

## Execution choices

- Replay remains the default, offline mode. Approval or budget options are
  rejected in replay. The existing `main(["--actual"])` guard still returns 2
  before output creation, credential checks, client loading, subprocesses, or
  network-capable code.
- Actual CLI execution requires explicit `--actual --approve-model-calls`,
  positive integer run-token, maximum-output-token, and maximum-model-call
  limits, a non-whitespace runtime `OPENAI_API_KEY`, and the pinned OpenAI SDK
  3.46.0. No actual-run limits were selected. The client uses the existing
  lazy factory, finite timeout, zero retries, `gpt-6-luna`, low reasoning, and
  the existing source-only request builder.
- The runner validates the corpus and reviewed reference, snapshots all nine
  generated source inputs and transformation manifests, and calls the same
  strict source contract used by the adapter/controller for every case before
  creating the SDK client. It observes seven approved cases and two
  preflight rejections; the rejected cases make no count or generation call.
  It then invokes the C1 workflow in catalog order with one caller-owned
  ledger, one client, and a fresh directory per approved case. Mutations remain
  offline replay controls.
- Independent scoring defaults to replay provenance. Explicit actual scoring
  accepts `current_model` only. It scores the last completed candidate even
  after checker rejection, keeps checker/workflow outcomes separate from field
  quality, and cannot trigger a retry or reference fallback. Earlier completed
  candidates stay scoreable if a later controller attempt aborts. A dispatched
  generation with no usable candidate is unscorable; a case with no
  generation/candidate is not-scored.
- Reports retain all nine planned rows. For the seven approved cases, fixed
  denominators are 147 value slots, 119 required-text atoms, and 77
  prerequisite atoms. Planned, actually scored, unscorable, and not-scored
  counts remain visible. Exit 0 indicates a complete, integrity-preserving
  measurement, not perfect extraction. Qualitative review remains pending.
- Actual failure receipts use fixed stage/failure codes and allowlisted error
  categories. The outer failure boundary blocks the ledger before best-effort
  reporting. It omits credentials, environment contents, provider exception
  bodies/messages, headers, and native client representations. Checker,
  renderer, and replay subprocess environments have `OPENAI_API_KEY` removed.
  Ctrl+C and SIGTERM abandon the local run with exit 130; the record does not
  infer that provider processing was cancelled.
- The programmatic injected-client seam is explicit and cannot silently
  replace the CLI factory. Every injected run records
  `execution_kind=injected_test` and `not_model_accuracy=true`. Tests block
  Python socket operations and use the real ledger, adapter, controller,
  checker, and renderer.

The actual command and its required options are in README.md. Its three limit
values are placeholders for caller choices after request review and count
planning. A frozen source corpus does not make actual model generation
offline.

## Initial offline verification checkpoint

The specified offline commands, complete outputs, and exit codes are retained
in `out/exam/task-014/c2-review/verification.log` inside the review bundle
`out/exam/task-014/task-014-phase-c2-review.zip`. The bundle contains the
working files, complete tracked and new-file diff, Git status, protected-file
hashes, skeleton-tag verification, and one explicitly injected actual-run
report with its ledger. It is copied to
`/mnt/c/Users/barza/Downloads/task-014-phase-c2-review.zip`.

The final specified check sequence passed all eight commands with exit code 0:
25 new injected actual-interface tests, 27 existing evaluation tests, and 20
shared-controller tests; all nine corpus cases validated; offline replay
passed; shell syntax, the offline dry-run, and whitespace checks passed. The
separate repository probe check and full repository test discovery were not
run. The replay itself exercised the existing local course checker.

This phase used injected clients only. No real HTTP/model request, source
collection, paid example, measured evaluation, qualitative review, package
installation, delegation, stage, commit, push, tag, or PR change occurred.
The historical live pilot remains a separate checkpoint and was not altered.


## Evidence and accounting repair

Nine new regression controls failed against the initial implementation: eight
failures and one error. The cases covered count requests without an affordable
reservation, missing/altered completed-case evidence, primary-failure retention,
summary-component failure and factual-quality reporting in Markdown.

The repair observes raw count/generation invocations through one pass-through
facade around the same native client and records only safe request metadata.
It does not add requests, retries or budgets. Completed cases require intact
source, candidate, checker, renderer and result receipts before the next case.
Failure reporting keeps the first cause and separate cleanup/report failures;
an independent fallback remains usable if the main summary component fails.
The manifest precedes the final atomic result receipt. Markdown now exposes
correct/missing/incorrect values and required-text/prerequisite coverage.

All 38 injected C2 tests passed after repair. Four additional cases exercise
failed audit persistence, conservative reservations, final-report ordering and
client-close failure. Full ordinary-WSL verification with the pinned SDK and
MCP is the next check. The measured model evaluation and qualitative review
remain pending.

Broader offline verification passed all 249 available SDK-independent tests
with no skips. The MCP and native OpenAI SDK contract modules were excluded
from that run because their dependencies are unavailable in the review
environment. Corpus validation, offline replay, both runner dry-runs, shell
syntax, the offline probe/checker and whitespace inspection also passed.
These results remain separate from pending full ordinary-WSL verification.

## Completed ordinary-WSL verification checkpoint

The ordinary-WSL evidence is retained under
`out/exam/task-014/wsl-c2-review-tojpnlz2/`. All **11 recorded commands
exited 0**, including the complete suite of **268 tests with zero skips**.
All **20 preserved hashes matched**. The protected set of 70 tracked files,
seven-path scope, runner mode, and annotated `compulsory2-skeleton` tag checks
passed. See `verification.log`, `commands.json`, and the before/after hash
manifests for the recorded results.

The suite and injected actual-interface tests establish application and
contract behavior with synthetic responses. They are distinct from provider
execution and do not establish model accuracy, live token-count agreement, or
provider-side budget enforcement. The measured fixed-set model evaluation,
qualitative review, and live normal-workflow demonstration remain pending.
Phase C2 has not yet run in GitHub Actions. Earlier checkpoints above remain
historical records.
