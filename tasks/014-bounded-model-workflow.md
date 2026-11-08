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

## Phase B1 scope and acceptance criteria (recorded before implementation)

Phase B1 adds only the following six paths:

- `tasks/014-bounded-model-workflow.md`
- `docs/meetings/2026-11-07-budget-design.md`
- `requirements-model.txt`
- `tests/test_openai_course_sdk.py`
- `.github/workflows/checks.yml`
- `README.md`

Pin `openai==3.46.0`. Use the already installed isolated SDK environment and
inspect its real OpenAI and HTTPX2 interfaces before implementation. Add
offline contract tests around the existing `OpenAICourseClient` and
`TokenLedger`, using the real SDK count/create methods with HTTPX2's native
in-memory `MockTransport`. The transport must use a synthetic API key and an
explicit `.invalid` origin; it must not use runtime credentials or make
network requests. Contract tests must fail clearly when the SDK is missing or
incompatible. Keep the existing SDK-independent Phase A tests unchanged.

The tests must verify identical serialized count/create input, instructions,
schema, model, and reasoning settings; output cap and response-only defaults;
durable reservation before generation dispatch; usage parsing with cached
input and reasoning details charged once; reuse of one ledger and refusal of
an unaffordable request; count/create HTTP failures with exact request counts
and automatic retries disabled; timeout retention and blocking; malformed
and contradictory usage including boolean/string token fields; and
incomplete, unexpected-model, tool, and refusal outputs. All requests and
responses are synthetic test fixtures. Never retain authorization headers,
raw credentials, or client representations.

Update CI to install `requirements-mcp.txt` and `requirements-model.txt`,
explicitly verify OpenAI version `3.46.0` and required imports before test
discovery, preserve current checks, permissions, and triggers, and make no
credential-bearing or model calls. Update README dependency and test
instructions. Record signature inspection and actual Phase B1 test results in
this task and the budget design record, while preserving earlier checkpoints.

Run `tests/test_openai_course_sdk.py` and both Phase A suites with the
provided isolated SDK Python. Run `git diff --check` and verify all existing
implementation code, checkers, fixtures, permissions, and tests remain
unchanged. Save exact commands, outputs, and exit codes under ignored
`out/exam/task-014/`, and create
`out/exam/task-014/task-014-sdk-contract-review.zip` containing only the six
scoped files and verification evidence. Do not install packages, collect
sources, run models, wire production/evaluation, stage, commit, push, or create
tags. Leave complete SDK-plus-MCP repository verification for ordinary WSL.

If a contract test reveals an adapter or ledger defect, preserve the failing
regression and its output without weakening validation or changing production
code in B1. Live provider validation, credentials, production integration,
and actual evaluation remain pending.

### Historical Phase B1 execution results before raw-response repair (2026-11-07)

The isolated environment and SDK signatures matched the successful saved
inspection: Python 3.12.3, OpenAI 3.46.0, HTTPX2 2.16.0; the real count/create
methods accept the request contract, and HTTPX2 provides native
`MockTransport(handler)`. No network or provider call was made.

- `test_openai_course_sdk.py`: **9 tests run, 2 failures, exit code 1**. The
  real SDK response parser coerces raw JSON `true` to integer `1` and string
  `"50"` to integer `50`; the existing adapter then accepts both as valid
  usage. The failing boolean and string regressions remain in the suite and
  their exact output is preserved. Production code was not changed.
- `test_model_budget.py`: **19 passed**, exit code 0.
- `test_openai_course_client.py`: **37 passed**, exit code 0.
- The Phase A suites were unchanged. Complete SDK-plus-MCP repository
  verification remains for ordinary WSL.

Commands and outputs are in `out/exam/task-014/phase-b1-sdk-suite.log`,
`out/exam/task-014/phase-b1-sdk-suite-regression.log`, and
`out/exam/task-014/phase-b1-phase-a-1.log` through
`out/exam/task-014/phase-b1-phase-a-2.log`. Live provider validation,
credentials, production integration, actual evaluation, and provider-side
enforcement remain **NOT RUN**. The scoped files and verification evidence
are packaged in `out/exam/task-014/task-014-sdk-contract-review.zip`.


## Raw-response repair scope and results (2026-11-07)

The Phase B1 SDK tests exposed a boundary error: typed SDK response models
converted JSON booleans and numeric strings before the ledger could check
original token types. Successful Python argument binding and the earlier
SDK-independent tests did not detect that conversion.

This repair changes six paths:

- `harness/openai_course_client.py`
- `tests/test_openai_course_client.py`
- `tests/test_openai_course_sdk.py`
- `README.md`
- `tasks/014-bounded-model-workflow.md`
- `docs/meetings/2026-11-07-budget-design.md`

The B1 requirement pin and workflow configuration remain unchanged. Combined
with the existing B1 work, the checkpoint therefore has eight changed/new
paths. `harness/model_budget.py`, all checkers, frozen source/reference data,
production runners/prompts/schema, and permission profiles are unchanged.

The adapter requires the SDK's public `with_raw_response` count/create
methods. It decodes the native HTTP response bytes directly with the standard
JSON parser, checks the endpoint's JSON object type, and never invokes typed
SDK response-model parsing for accounting. Boolean, string, and floating-point
token fields retain their original types and fail the existing exact-integer
checks. Missing raw interfaces fail before any count/generation request;
there is no fallback to a converted SDK model.

Invalid JSON, duplicate fields, nonstandard numeric constants, incorrect
response objects, and malformed usage detail objects stop the run. Count
failures cannot dispatch generation; generation failures retain their
reservation. Native responses are closed after reading. Only allowlisted
request IDs from response headers are used for request provenance. The
immutable shared request, output cap, reservation order, zero SDK retries,
and same-ledger accounting remain unchanged.

SDK-independent test doubles now expose raw HTTP responses. The SDK-free
fresh-checkout check remains intact. The post-settlement fault test injects
an output-processing failure after known usage has settled, preserving its
original failure-containment requirement. The real SDK's boolean/string
regressions remain unchanged; additional native transport cases cover raw
count types, malformed response JSON, and duplicate fields.

Verification available at this repair checkpoint:

- Against the unchanged adapter, eight SDK-independent raw-boundary tests
  failed with 24 subtest failures, exit 1. The uploaded real-SDK checkpoint
  separately preserves its original nine tests and two coercion failures.
- After repair, **45 adapter tests and 19 ledger tests passed** (64 focused
  tests, zero skips). All **159 available SDK-independent course/evaluation/
  budget tests passed**, zero skips. This review copy excludes the existing
  weather/MCP modules and does not contain the pinned SDK installation.
- The extended real-SDK suite has **12 tests**; its post-repair execution
  remains **NOT RUN** until ordinary WSL verification. Complete SDK-plus-MCP
  repository verification also remains **NOT RUN** at this checkpoint.
- Exact local results and original B1 evidence are retained in the repair
  package. No provider/model calls, live token measurements, credentials,
  source refresh, production integration, staging, commit, push or tag
  operation was performed in the target repository.

The adapter remains unwired and actual evaluation remains disabled. The next
verification must run the pinned SDK's in-memory contract suite first. Only
if it passes should the model dependency be installed in the project test
environment and the complete SDK-plus-MCP suite run. These local checks do
not establish provider count agreement, provider enforcement, or model
quality; those later gates remain pending.

## Completed ordinary-WSL Phase B1 verification checkpoint

The completed ordinary-WSL evidence is preserved in
`out/exam/task-014/wsl-sdk-raw-4lIzvr/verification.log`, with installed
package versions in `installed-versions.txt` and preserved-file hashes in
`preserved-files.sha256`.

- The real-SDK contract suite passed **12 tests**, including the retained
  boolean/string usage regressions. These tests use synthetic responses via
  the SDK's in-memory HTTP transport; they are not live provider validation.
- The ledger suite passed **19 tests** and the SDK-independent adapter suite
  passed **45 tests**.
- The complete repository suite passed **208 tests with zero skips**.
- OpenAI **3.46.0** was installed alongside MCP **2.3.0**; `pip check` passed.
- Shell syntax, both workflow dry-runs, corpus/reference checks, offline
  replay, and offline probe/checker passed. Replay evidence is at
  `out/course-evaluations/run-20261107T182117.009130Z-d18a4d01`.
- All seven preserved-file checksums matched. Protected-code and exact
  checkpoint-scope checks passed. Verification exit code: **0**.

This checkpoint records local SDK contract compatibility and synthetic
transport behavior only. Credentials, live count agreement, provider
enforcement, production integration, and actual evaluation remain pending.
Actual evaluation remains disabled. Earlier Phase A and B1 checkpoints above
remain historical evidence.

## Phase C1 normal-run integration (2026-11-08)

This bounded phase changes only the eight authorized paths: the new shared
`harness/course_workflow.py`, the thin `harness/run_courses.sh` wrapper, the
new `tests/test_budgeted_course_workflow.py`, updated
`tests/test_course_workflow.py`, `README.md`, `SPEC.md`, this task record, and
`docs/meetings/2026-11-08-budget-integration.md`. The ledger, adapter, source
collector, production checker, renderer, prompt, schema, fixed corpus and
reference, SDK contract tests, and `harness/evaluate_courses.py` are unchanged.
Actual evaluation remains disabled.

The shared controller takes a source bundle, caller-owned `TokenLedger`,
injected SDK client, and a fresh case evidence directory. It preflights and
detaches the source before provider dispatch, then uses the existing adapter
for each count/reserve/create/settle attempt. The same ledger can be passed to
successive case invocations. Only completed checker exit code 1 is retryable;
the rejected JSON and exact complete checker output go through the existing
repair contract. Malformed repair data, uncertain API outcomes, timeouts,
checker failures, and renderer failures stop without retry. The controller
keeps each candidate and component evidence in the case directory and renders
only after acceptance. The normal CLI uses one run ledger and is the sole
publisher of the two normal output files.

The wrapper resolves the repository root, selects the project virtualenv
Python when present, and otherwise uses `python3`. Actual CLI use requires
`OPENAI_API_KEY` and positive `--run-token-limit`, `--max-output-tokens`, and
`--max-model-calls`; missing or invalid values fail before collection or
output creation. `--offline` affects source collection only. Dry-run creates
no files, collects no source, invokes no checker/renderer, and constructs no
client. Collector, checker, and renderer subprocesses have the API key removed
from their environments. Normal JSON and Markdown publication happens only
after checker acceptance and successful rendering. The pair of output-file
replacements is not claimed to be atomic.

### Provider checkpoint and separate pilot score

The exact checkpoint artifacts under
`out/exam/task-014/live-20261108T083934Z-72p24bam/` were reviewed. The observed
run used `gpt-6-luna`, runtime reasoning `low`, OpenAI SDK 3.46.0, and zero SDK
retries. Input counted and completed input usage both measured 4,414 tokens;
output was 1,801 tokens including 163 reasoning tokens, and total usage was
6,215. The output cap was 12,000, the run limit 16,414, and 10,199 tokens
remained after settlement. There were two input-count requests across
planning/execution and one generation. The ledger refused another request
before either endpoint was touched while one of two model-call slots remained.
The candidate checker passed, protected files were unchanged, and the probe
exited 0. Count and create shared payload hash
`a40cb8bf09448efa6193724efe81abe8b19e287433cf78bfae95f9f9ceacddb7`.

This is one observed count/usage agreement and pre-dispatch budget refusal.
The provider output cap was supplied and not exhausted. This is not a dollar
spending guarantee, a production-integration result, or a nine-case
evaluation.

The unchanged candidate was independently scored against reviewed `S00-base`
with `course_evaluation_scoring.score_candidate(...,
provenance="recorded_model")`. Recomputed results are in the ignored
`out/exam/task-014/live-20261108T083934Z-72p24bam/independent-pilot-score.json`:
20/21 value slots correct, 17/17 required text atoms covered, and 11/11
prerequisite atoms covered. The single incorrect slot is
`robot-delivery-format`, where a supported value is also listed as missing.
This is one pilot, not overall model accuracy. The candidate, checker, prompt,
and benchmark were not changed; qualitative review of the complete evaluation
set remains pending.

### Initial Phase C1 offline verification checkpoint

The following checks passed from the repository root:

- `bash -n harness/run_courses.sh`: exit 0.
- `./harness/run_courses.sh --offline --dry-run`: exit 0; no source collection,
  client construction, API call, component subprocess, or file creation.
- `./harness/run_courses.sh --dry-run`: exit 0 with the same no-side-effect
  behavior.
- `.venv/bin/python -m unittest discover -s tests -p 'test_budgeted_course_workflow.py'`:
  11 tests passed, exit 0.
- `.venv/bin/python -m unittest discover -s tests -p 'test_course_workflow.py'`:
  5 tests passed, exit 0.
- `python3 harness/course_evaluation_cases.py --check`: 9 source cases passed,
  exit 0.
- `python3 harness/evaluate_courses.py --replay`: offline component replay
  passed as `run-20261108T091519.912146Z-44c4ba61`, exit 0.
- `git diff --check`: exit 0.
- `python3 harness/probe.py --offline` and `python3 eval/check_probe.py`:
  both passed; checker output `PASS`, exit 0. The pre-existing ignored
  `out/probe.json` hash was unchanged at
  `ed8bce3c90d9ed0617e32527480293d881872afa126d29adde4f694c112c3749`.

The branch remains `exam/budget-enforcement` at
`1e881e5a9e2aa178956d8018f9a4f2f19c32c414`; annotated tag
`compulsory2-skeleton` still targets commit
`11e057ecd28387674b64bca96f3687bd1ca15643` (tag object
`e8d594e70f2eb655327ec2e321c6b2822bc9de3e`). The runner remains mode 100755.
The changed and new path set matches the eight authorized paths, and protected
files have no working-tree diff. No files were staged, committed, pushed, or
tagged. The complete SDK/MCP repository suite remains for ordinary WSL after
review. No paid normal run or actual evaluation was performed in this phase.

Review delivery: `out/exam/task-014/task-014-phase-c1-review.zip`, with the
same archive copied to Windows Downloads.

### Phase C1 failure-containment review and repair — 2026-11-08

Controlled faults exposed gaps after the initial focused checks. A failed
renderer-receipt write was ignored, allowing an accepted result; source
snapshot I/O was classified as source rejection; and component interruption
could escape with an open shared ledger. Separate context/provenance/result
write faults also lacked a complete abandonment boundary. A later case could
therefore dispatch after an infrastructure failure.

The extended controller suite against the unchanged C1 implementation ran
20 tests with 5 failures and 3 errors, exit 1. The repair adds a case-level
abandonment boundary, blocks the existing ledger before best-effort error
receipts, separates data validation from context/storage errors, and requires
renderer evidence before acceptance. Unexpected native error text is not
logged. Interrupted cases return a structured abandoned result; the CLI
uses exit 130. No ledger/adapter/checker/reference change was required.

After repair, all 20 controller tests and 12 CLI tests passed. CLI coverage
includes source-collection failure/staleness, provider timeout, empty output,
budget exhaustion, rendering failure, prior-publication preservation, and
execution outside the repository. Token-budget tests separately demonstrate
sharing across retries and cases with call slots still available.

The broader available SDK-independent suite passed 211 tests with zero skips.
Its explicit exclusions were `test_mcp_met.py` and
`test_openai_course_sdk.py`, whose dependencies were unavailable in the review
environment. Syntax, both previews, corpus validation, offline replay and
offline probe/checker passed. This is offline controller regression evidence,
not a complete SDK/MCP result, paid normal run, actual evaluation, or the
completed exam stress-testing study. Full ordinary-WSL verification remains
pending. Frozen inputs, the pilot candidate and all unrelated code remain
unchanged; nothing was staged, committed, pushed or tagged.

### Completed ordinary-WSL Phase C1 verification — 2026-11-08

The completed verification evidence is preserved under
`out/exam/task-014/wsl-c1-review-2n94oqjf/`. The full ordinary-WSL test
discovery run passed all 230 tests with no skips. All 11 recorded verification
commands exited 0, and all 20 preserved-file hashes matched before and after
verification. The eight-path scope, protected-file, runner mode 100755, and
`compulsory2-skeleton` tag checks passed. Earlier checkpoints above remain
historical records of their own verification runs.

Actual evaluation and a live normal-workflow run remain pending. This
checkpoint does not claim either result.

## Phase C2 actual evaluation interface (scope and implementation record)

Phase C2 changes only these seven paths: `harness/evaluate_courses.py`,
`harness/course_evaluation_scoring.py`, the new
`tests/test_actual_course_evaluation.py`, `README.md`, `SPEC.md`, this task
record, and `docs/meetings/2026-11-08-course-model-evaluation.md`. The shared
controller, ledger, adapter, frozen inputs, reference, checker, renderer,
collector, prompt, schema, requirements, CI, permission profiles, W43 material,
and existing tests remain outside the change set.

### Interface and execution decisions

- Default execution remains offline replay. Replay rejects approval and
  budget options and does not inspect credentials or construct an SDK client.
  Actual CLI execution requires `--actual --approve-model-calls` plus explicit
  positive `--run-token-limit`, `--max-output-tokens`, and
  `--max-model-calls` values. No live limits are defaults or selected here.
- The real path checks the runtime-only `OPENAI_API_KEY`, rejects whitespace
  keys, and verifies the installed SDK against `requirements-model.txt`'s
  `openai==3.46.0` pin before it creates evidence or a client. It uses the
  existing lazy SDK factory, finite timeout, zero retries, `gpt-6-luna`, low
  runtime reasoning, and the existing source-only request builder. Checker,
  renderer, and replay subprocesses receive environments with the API key
  removed.
- Actual mode validates the fixed corpus and reviewed reference, snapshots the
  generated source cases and transformations, and observes the same strict
  adapter/C1 source contract for all nine cases before client construction.
  The two expected preflight rejections make zero count/generation requests.
  Each of the seven approved inputs runs through
  `course_workflow.run_course_workflow` in catalog order using one caller-owned
  ledger, one client, and a new case directory per invocation. Candidate
  mutations remain replay controls.
- The scorer's default mode remains replay and keeps its existing provenance
  classes. Explicit actual mode accepts only `current_model`. It independently
  scores the last completed candidate, even when the checker rejected it, and
  never supplies score results to the controller. A candidate retained from
  an earlier completed attempt is scored and labelled if a later attempt
  aborts. A dispatched generation without a usable candidate is recorded as
  unscorable; a case with no generation/candidate is not-scored.
- Workflow/checker outcomes are recorded beside, but separately from, field
  scores. The fixed approved set keeps 147 value slots, 119 required-text
  atoms, and 77 prerequisite atoms in its denominators. Reports distinguish
  planned, actually scored, unscorable, and not-scored coverage. Exit 0 means
  all nine case outcomes and required artifacts were finalized with integrity
  preserved; it does not mean perfect extraction. Qualitative review remains
  pending.
- The actual-mode failure boundary blocks the shared ledger before safe
  failure reporting. Actual receipts use fixed stage/failure codes and
  allowlisted error categories; provider exception messages, response bodies,
  headers, client representations, credentials, and environment values are
  not serialized. Interruption exits 130 and does not assert that provider
  processing stopped.
- The programmatic test seam requires an explicit client factory and records
  `execution_kind=injected_test` and `not_model_accuracy=true`. It is not
  exposed as a CLI simulation mode. Tests use the real C1 controller, ledger,
  adapter, checker, and renderer with injected raw responses and blocked Python
  socket operations.

The actual CLI form is documented in README.md with placeholders for the three
caller-selected limits. Frozen source input does not make model generation
offline. The measured evaluation limits will be selected only after request
review and count planning.

### Initial Phase C2 verification checkpoint

Verification commands and their exact outputs, exit codes, protected-file
hashes, skeleton-tag check, Git status/diff, and the injected actual report and
ledger are recorded in the C2 review bundle under
`out/exam/task-014/task-014-phase-c2-review.zip`. This phase exercised the
actual interface only with injected clients. No provider call, source
collection, measured model run, qualitative review, staging, commit, push,
tagging, or PR change was performed. The review bundle is also copied to the
Windows Downloads path requested for this task.

The final specified check sequence passed all eight commands with exit code 0:
the new injected actual-interface suite passed 25 tests, the existing replay
suite passed 27, and the shared-controller suite passed 20. The corpus check
validated all nine cases; offline replay, shell syntax, the offline dry-run,
and `git diff --check` passed. The complete output is in
`out/exam/task-014/c2-review/verification.log`. No provider-mode CLI, full
repository suite, separate probe check, or source collection was run. The
fixed-case replay did run its existing local course checker.


### Phase C2 evidence and accounting repair — 2026-11-08

Nine additional regression controls exposed eight failures and one error in
the initial C2 implementation. A completed count followed by an unaffordable
reservation was absent from request totals. Missing/changed case artifacts
could leave a complete report and allow subsequent dispatch. Reporting errors
could replace the first failure or fail again in the same summary component.
The Markdown report also omitted independent factual-quality counts.

The repair adds a pass-through audit around the same native SDK client, with
safe invocation receipts independent of reservations. The existing adapter
still owns count validation, reservation, generation and settlement. Completed
case receipts and hashes are verified before continuing; the controller,
ledger, adapter, checker, frozen inputs and references remain unchanged.
A failed audit write stops dispatch, including before an endpoint invocation;
conservative reservations remain if its generation slot was already marked.
The first failure and later report/close failures are recorded separately.
An independent minimal failure receipt handles a broken summary component.
The manifest is written before the atomically replaced final result receipt.
Both JSON and Markdown show factual quality with explicit denominators.

The injected C2 suite passed 38 tests, including the nine repaired controls
and four additional audit/finalization cases. These tests exercise application
behavior with injected SDK responses; they do not measure provider accuracy.
Full SDK/MCP-enabled ordinary-WSL verification remains pending.

Broader offline verification passed all 249 available SDK-independent tests
with no skips. The MCP and native OpenAI SDK contract modules were excluded
from that run because their dependencies are unavailable in the review
environment. Corpus validation, offline replay, both runner dry-runs, shell
syntax, the offline probe/checker and whitespace inspection also passed.
These results remain separate from pending full ordinary-WSL verification.

## Completed ordinary-WSL Phase C2 verification checkpoint (2026-11-08)

The ordinary-WSL verification evidence is preserved in
`out/exam/task-014/wsl-c2-review-tojpnlz2/`. All **11 recorded commands
exited 0**. The complete repository suite ran **268 tests with zero skips**.
All **20 preserved tracked-file hashes matched**. The 70 protected tracked
files, seven-path change scope, runner mode, and annotated
`compulsory2-skeleton` tag checks passed. The complete log is
`verification.log`; command results and before/after hash manifests are in
`commands.json`, `preserved-files-before.json`, and
`preserved-files-after.json`.

This checkpoint verifies offline, injected/contract behavior and repository
integrity. The injected tests use synthetic responses and do not constitute
provider execution or evidence of model accuracy, provider count agreement,
or provider-side budget enforcement. No live model request or source
collection was made during this verification. The measured fixed-set model
evaluation, qualitative review, and live normal-workflow demonstration remain
pending. Phase C2 has not yet run in GitHub Actions. Earlier Phase A, B1, and
C2 checkpoints above remain historical records of their own results.

## First measured fixed-set course evaluation — 2026-11-08

The predeclared provider evaluation completed with intact evidence on the
frozen nine-case set. Seven approved cases were independently scored, including
both final candidates rejected by the workflow; two unapproved sources were
rejected before count or generation. First-attempt acceptance was 4/7 and
final workflow acceptance was 5/7. Scores were 144 correct, zero missing, and
three incorrect of 147 declared values; required-text and prerequisite phrase
coverage was 119/119 and 77/77. These are fixed-set measurements, not estimates
of accuracy on unseen courses. Detailed findings and retained evidence are in
`docs/meetings/2026-11-08-measured-course-evaluation.md`.

This is a documentation checkpoint only. It did not rerun tests, collection,
or model calls. Keep this run as the baseline and keep references frozen.
Future implementation work may attach trusted source metadata and derive
internally consistent missing-field flags in Python while the model extracts
evidence-grounded facts. Ambiguous-offering dates still require abstention;
any improvement is a separately declared trial. Student confirmation, the
live normal-workflow demonstration, complete stress study, and final exam
delivery remain pending.
