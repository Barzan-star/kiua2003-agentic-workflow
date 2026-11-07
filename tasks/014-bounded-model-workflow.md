# Task 014: Budgeted model calls for the course workflow

## Goal and baseline

Add an enforceable token budget to course extraction before enabling actual
model evaluation. The starting commit is
`c520589827f0a6a9475f7a79c75a83505818b65d`, on branch
`exam/budget-enforcement`. Task 013 passed 132 tests in ordinary WSL, PR #6
was merged, and main-branch CI run `42379946677` succeeded.

The exam requires a per-run token or cost budget and a mechanism that enforces
it. This task chooses **total model input plus output tokens**. It does not
claim a dollar spending ceiling. Current model-call timeouts, retry counts,
and post-call usage logs are separate protections.

## Implementation sequence

**Phase A (current scope):** implement the token ledger, isolated extraction
request builder, and a real Responses API adapter, tested with injected SDK
test doubles. Keep the adapter unwired from production and evaluation
commands. No API key, SDK installation, network request, source collection,
or actual model execution is needed for these tests. The live SDK factory
must be lazy. Mocked tests establish application behaviour, not observed
provider enforcement.

**Phase B (later):** install and pin a verified compatible OpenAI Python SDK;
configure the API key outside project files; verify the token-count interface;
select explicit numerical limits; and review the real request contract.

**Phase C (later):** add shared, budgeted orchestration for normal extraction
and actual evaluation. Preserve one extraction/check/retry implementation and
the existing source evidence, schema, checker, and renderer contracts. One
budget covers the entire invocation, including every retry and, for an
evaluation batch, every source case. Enable actual mode only after the
budget, input isolation, and live bounded-call checks pass.

Phase A may add/change only:

- `tasks/014-bounded-model-workflow.md`
- `harness/model_budget.py`
- `harness/openai_course_client.py`
- `tests/test_model_budget.py`
- `tests/test_openai_course_client.py`
- `docs/meetings/2026-11-07-budget-design.md`

Keep all existing tracked files unchanged. In particular preserve `eval/`,
the Phase A corpus/reference, the accepted source fixture, existing tests,
production runners/prompts/schema, permissions, requirements, and CI.
`harness/evaluate_courses.py --actual` remains disabled. Do not start a second
copy of the course workflow in Phase A.

## Verified API basis

Official documentation checked on 2026-11-07:

- [Per-run controller](https://developers.openai.com/cookbook/articles/per_run_spending_controller_responses_api):
  reserve an affordable request allowance before dispatch; disable SDK
  automatic retries; abandon a run when a submitted request's final usage is
  uncertain. Its offline example is not evidence of a real provider limit.
- [Token counting](https://developers.openai.com/api/docs/guides/token-counting):
  `POST /v1/responses/input_tokens` counts the model's full input; output
  limits include generated non-visible tokens, including reasoning.
- [Count request reference](https://developers.openai.com/api/reference/cli/resources/responses/subresources/input_tokens/methods/count):
  input counting supports the model, input/instructions, reasoning settings,
  text-format configuration, and tool configuration. The returned count is
  `input_tokens`.
- [GPT-6 Luna](https://developers.openai.com/api/docs/models/gpt-6-luna):
  the existing `gpt-6-luna` model supports Responses and structured output.

Use the existing model and low runtime reasoning effort. Do not invent a
Codex flag, SDK version, model snapshot, price, or provider capability. The
SDK version is selected and pinned in Phase B after its actual interface has
been inspected. Phase A's tests must run without the SDK installed.

## 1. Token ledger

Implement a small, importable ledger with explicit operations to reserve,
settle, and permanently block further dispatch. Require caller-supplied
positive integer token/output/call limits; reject booleans, strings, missing
values, zero, and negatives. Select no live numerical defaults in Phase A.
Synthetic limits in unit tests must be clearly test data.

For a request with counted input `I` and configured maximum output `O`, its
reservation is `R = I + O`. With run limit `B`, confirmed usage `U`, and
pending reservations `P`, admit dispatch only if:

`U + P + R <= B`

Also enforce the remaining model-call allowance. Count generation attempts
at dispatch, including failures whose usage is unknown. Reuse the same
ledger across retry attempts; creating a fresh ledger for a retry is invalid.
Check blocked/exhausted state before calling the token-count endpoint.

Persist the reservation successfully **before** generation dispatch. A
persistence error stops dispatch. Use a caller-supplied fresh ledger path in
the run evidence directory; refuse an existing ledger instead of resetting
it. Never open an existing ledger for implicit resume. Write updates
atomically. The caller owns the approved output-directory boundary; the
ledger must never overwrite an existing project file.

After a completed, trustworthy response, debit validated input plus output
usage and release the unused part of its reservation. Count cached input
once and do not add reasoning tokens again to `output_tokens`. Validate
integer types, nonnegative values, total consistency, matching counted input,
and the configured output ceiling. Do not turn missing usage into zero.

Timeouts, interrupted dispatch, transport exceptions, incomplete responses,
untrusted usage, or usage contradicting a request bound stop further calls.
Retain reservations when the actual charge is uncertain. Record observed
bound contradictions explicitly; do not claim that a contradictory provider
usage report proves a successful limit. A client timeout does not prove that
the provider stopped processing the request.

Reservation handles must be unique and cannot be settled twice. Keep the
implementation appropriate for one controlling process with serial requests.
Do not claim cross-process accounting. No automatic worker, subprocess,
background, or restart mechanism may bypass the ledger.

## 2. Isolated extraction request

Build requests deterministically from the selected source bundle, existing
extraction prompt and output schema, and optional preceding rejected JSON
plus exact production-checker feedback. Use the existing source preflight
and add explicit request-shape checks where necessary without changing it.
Unapproved courses/URLs must fail before any count or generation request.

The model input contains only the approved source data and extraction
instructions. Preserve source metadata and verbatim section text, and derive
explicit zero-based section indices as the current runner does. Refuse
unexpected source object/section fields rather than forwarding arbitrary
metadata. Treat source labels, text, and rejected candidates as untrusted.

Never include reference facts, evaluation manifests, case IDs/descriptive
case paths, scoring results, tests, local file contents, or credentials.
Production checker feedback is the only repair feedback. The independent
scorer must not become an answer-key feedback channel.

Send no model tools and no workspace/file access. Use stateless requests:
no server conversation, previous-response linkage, agent runtime, hosted
tools, delegation, streaming, or background execution. No output item may
cause local command/tool execution. Preserve the existing JSON-schema
contract and runtime model/effort; do not change extraction facts or the
existing prompt/schema files.

## 3. Responses adapter

Implement the actual supported SDK call path, with dependency injection for
offline tests. The live factory lazily imports `OpenAI`, reads only the
explicit runtime API-key environment variable, and sets `max_retries=0` and
a finite timeout. It must not read `.env`, Codex authentication storage, or
other credential files. Do not print credential values or raw client objects.
Do not install packages or construct a live client during import/tests.

The production request sequence is:

1. Validate source/request shape and budget state.
2. Build one immutable shared request payload.
3. Call `client.responses.input_tokens.count` with that payload.
4. Validate the count and reserve `I + O` in the same run ledger.
5. Call `client.responses.create` with the same model input, settings, and
   schema, plus `max_output_tokens=O` and the response-only options.
6. Validate response status/usage and settle, or block and retain uncertainty.

Use default service processing, `store=False`, and synchronous non-streaming
requests. Count and create must share exactly the supported input-affecting
fields, including the structured-output schema, instructions, and reasoning
configuration. Response-only options and local timeout controls are recorded
separately. Reject unsupported caller options. No payload changes may occur
after counting. Record hashes of the shared count/create input payloads.

Keep model-call accounting distinct from token-count requests. A failed or
malformed count must never dispatch generation. Do not automatically retry
either API operation. Only the later shared workflow may retry a completed
candidate rejected by the production checker, within the same budget.

Keep requested/returned model identifiers and safe response/request IDs for
audit. Unexpected model routing, refusals, tool output, absent output, or an
incomplete response are explicit model/protocol failures. Do not invent
snapshot aliases to accept a mismatch. Use safe, allowlisted error metadata;
API error messages/headers can contain secrets and must not be copied blindly
into prompts, console output, or evidence. Tests must include a synthetic
secret marker to establish that diagnostic paths do not expose credentials.

No numerical allowance, live SDK/account access, provider-count agreement,
or actual enforcement is claimed until the later live checks occur.

## 4. Evidence and tests

Use temporary directories and explicit injected SDK doubles. No network,
model, source collector, Codex subprocess, or delegation is allowed in this
phase. Meaningful tests cover at least:

- Invalid limit types and values; exact-boundary admission and refusal.
- Reservation before dispatch, settlement, reuse across attempts, exhaustion,
  call-count limits, duplicate settlement, and refusal to reset an old ledger.
- Persistence failure before dispatch and retained reservations after
  uncertain dispatch/usage; no further count or generation after blocking.
- Same full input/schema/settings for count and create; output cap present;
  SDK automatic retries disabled; invalid count prevents generation.
- Usage accounting with cached input and reasoning, malformed/missing usage,
  mismatched input/total, and output above its configured bound.
- Refusal, incomplete output, timeout, and unexpected tool/model output.
- Source rejection before any provider operation; explicit section indices;
  exclusion of extra metadata, reference answers, and secret markers.
- Fresh-checkout execution without SDK, API key, or existing `out/`.
- Original fixture, reference, code, tests, and normal outputs preserved.

The design record documents actual choices, test results, and remaining live
checks. It must distinguish unit evidence from provider evidence. Preserve
the Task 013 raw results and all earlier checkpoints.

## Phase A acceptance

Run the two focused suites and whitespace/protected-file checks; capture the
exact commands, output, and exit codes under ignored `out/exam/task-014/`:

```sh
python3 -m unittest discover -s tests -p 'test_model_budget.py'
python3 -m unittest discover -s tests -p 'test_openai_course_client.py'
git diff --check
git diff --exit-code HEAD
```

All commands are **NOT RUN** at specification time. Phase A adds only new
files, so the tracked-file diff must remain empty. After implementation,
record actual results without converting future checks into claimed results.
Leave the complete SDK/MCP-enabled repository suite for ordinary WSL after
review. Do not stage, commit, push, or create tags in this implementation step.

## Later acceptance gates

Before enabling actual course extraction/evaluation:

- Verify and pin the real SDK interface; configure credentials locally with
  no secret in the repository, prompts, or logs.
- Select explicit run/output/call limits and check the supported endpoint
  with the exact structured request, including schema and retry payload.
- Demonstrate a real bounded successful response and refusal before the next
  unaffordable generation request. Keep requests, usage, reservations,
  response metadata, and final run state as evidence.
- Route normal and evaluation runs through one shared controller. Preserve
  source/checker/retry/render contracts and prevent evaluation publication to
  normal training outputs. Share one invocation budget across all cases and
  retries; do not reset it per case.
- Establish that the model has no tools/file access and receives no benchmark
  answers or evaluation metadata. Verify failure containment and the explicit
  abandonment condition before measured model evaluation.
- Retain reproducible normal and evaluation commands, then run the actual
  fixed-set evaluation and the selected system stress tests. Unit tests alone
  do not satisfy these gates.

All later gates remain **NOT RUN**. The numerical budget, SDK installation,
credential configuration, shared workflow integration, and actual evaluation
are later work rather than blockers for Phase A's offline implementation.

## Historical initial Phase A checkpoint (2026-11-07)

- `python3 -m unittest discover -s tests -p 'test_model_budget.py'`: **PASS**,
  14 tests, exit code 0.
- `python3 -m unittest discover -s tests -p 'test_openai_course_client.py'`:
  **PASS**, 25 tests, exit code 0. The tests include a temporary fresh checkout
  with no `out/`, no API key, and OpenAI SDK imports blocked.
- `git diff --check`: **PASS**, exit code 0.
- `git diff --exit-code HEAD`: **PASS**, exit code 0; no tracked file changed.
- `python3 harness/probe.py --offline && python3 eval/check_probe.py`: **PASS**,
  output `PASS`, exit code 0. The existing `out/probe.json` was restored
  byte-for-byte after this repository check.
- The full repository suite was **NOT RUN**, as directed for ordinary WSL
  review. Actual evaluation, SDK installation, live credentials, network
  calls, model execution, numerical live limits, and provider enforcement are
  **NOT RUN**.

Exact command output and exit codes are in `out/exam/task-014/`. The
implementation and verification logs are packaged in
`out/exam/task-014/task-014-budget-review.zip`. These results establish local
unit behavior only; they do not establish provider-side enforcement or count
agreement. See
`docs/meetings/2026-11-07-budget-design.md` for implementation decisions and
the remaining Phase B/C checks.


## Historical Phase A failure-containment repair checkpoint (2026-11-07)

The initial 39 focused tests passed. Additional fault tests found that run
limits could be reassigned, interrupted persistence could leave a ledger
open, and an output accessor failure after settlement did not permanently
stop the run. The adapter also accepted clients with automatic retries,
left failed count operations open to another attempt, and could expose an
exception raised while accessing a count response. Malformed nested repair
containers and credential-shaped audit identifiers needed stricter checks.

The repair is confined to the same six Phase A paths:

- Run limits are read-only for the lifetime of a ledger. Each reservation
  records its own output ceiling, and settlement checks that ceiling and the
  full reserved allowance. Incomplete responses retain their reservation
  and record any observed numeric bound contradiction. Persistence interruptions block the in-memory run
  and preserve existing reservations; persistence errors use safe messages.
- The adapter verifies zero SDK retries and a finite positive numeric timeout
  before counting, then verifies that contract again after counting. Count
  failures, malformed counts, and interruptions abandon the run without
  inventing a generation charge. Errors after settlement retain confirmed
  usage and permanently block further count/generation operations.
- Repair input checks nested container and scalar types as well as field
  names. Audit IDs use field-specific prefixes and permitted characters;
  arbitrary provider diagnostics are not treated as identifiers. These shape
  checks are not a general-purpose secret detector: callers still must not
  insert credentials or evaluation answers into source/candidate text.
- Create explicitly sends `service_tier="default"`, `background=False`,
  `store=False`, and `stream=False`. These response-only options, retry policy,
  and timeout are recorded separately from the shared input hash. The lazy
  factory sets the official API base URL explicitly rather than inheriting
  an `OPENAI_BASE_URL` override. No SDK is installed or constructed in tests.

### Verification of the repair

- The expanded tests against the original implementation failed as expected:
  ledger 19 tests, 8 failures and 1 error; adapter 37 tests, 17 failures and
  2 errors. Unittest counts include subtest failures.
- After repair: ledger **19 passed**, adapter **37 passed**; **56 focused
  tests passed** in total. The adapter tests include an SDK-free fresh
  checkout and reuse of one ledger until a later request is unaffordable.
- The available course/evaluation/budget component suite passed **151 tests**.
  This is not the complete repository suite: the review copy does not include
  the existing weather/MCP test modules. Full ordinary-WSL verification is
  still **NOT RUN** at this checkpoint.
- Existing source, corpus/reference, production checker, prompts/schema,
  orchestration, evaluation implementation and existing tests are unchanged.
  The six repaired files pass the whitespace comparison check.
- Original upload logs and pre/post-repair test output remain available in
  the repair package. No live SDK, credential, provider request, model run,
  source refresh, staging, commit, push or tag operation was performed.

The adapter remains unwired. Phase B's real SDK/interface checks and Phase C's
shared orchestration and actual evaluation gates remain **NOT RUN**. Passing
these offline tests does not establish provider token-count agreement or
observed provider enforcement. The ledger assumes a trusted controlling
process with serial requests; it is not a sandbox against code deliberately
modifying its private state or sending requests outside the controller.

## Completed ordinary-WSL Phase A verification (2026-11-07)

The completed ordinary-WSL verification is preserved in
`out/exam/task-014/wsl-review-rglNnf/verification.log`; its protected-file
hash list is `out/exam/task-014/wsl-review-rglNnf/preserved-files.sha256`.

- Corpus/reference check passed for nine source cases.
- Offline component replay passed:
  `out/course-evaluations/run-20261107T162557.247516Z-3b26e9fd`.
- Offline probe and checker passed.
- All 188 repository tests passed.
- All seven preserved-file checksums matched.
- Verification exit code: **0**.

This completes the offline Phase A checkpoint only. The adapter remains
isolated and unwired, and actual evaluation remains disabled. SDK installation,
live requests, provider count agreement, and provider enforcement remain
**NOT TESTED**. Earlier checkpoints above are historical records of their
respective review stages.
