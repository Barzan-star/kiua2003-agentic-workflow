# Budgeted model workflow: Phase A design record

Date: 2026-11-07
Scope: Phase A of Task 014 only
Status: implemented and checked offline; adapter remains unwired

## Implementation choices

- `TokenLedger` requires a caller-selected run token limit, output token cap,
  maximum model-call count, and a fresh path in an already-created evidence
  directory. It rejects non-integer and non-positive limits, refuses an
  existing ledger, and never resumes one. State updates use a same-directory
  temporary file, `fsync`, and atomic replacement guarded by the identity of
  the file created by the ledger.
- A counted input reservation is `input_tokens + max_output_tokens`. The
  complete reservation is persisted before the generation dispatch marker;
  that marker increments the model-call attempt count before the SDK call.
  Confirmed usage releases unused reservation. Unknown or invalid usage keeps
  the reservation and permanently blocks the in-memory run and its evidence
  state. Input mismatch and output above the configured cap are recorded as
  explicit bound contradictions.
- Input and cached input are charged once as `input_tokens`; output and
  reasoning are charged once as `output_tokens`. Usage must use exact integer
  fields, match the count, fit the configured output cap, and satisfy
  `total_tokens == input_tokens + output_tokens`.
- The request builder first calls the existing source preflight and then
  enforces exact top-level, course, and section fields. It copies the
  approved source metadata and verbatim section text, derives zero-based
  indices, and includes only the existing extraction prompt and JSON schema.
  Repair input is limited to a preceding candidate JSON string and the exact
  production-checker feedback string supplied by the later shared workflow.
- Count and create use independent SDK dictionaries decoded from the same
  immutable canonical JSON bytes. Their shared fields are model, instructions,
  input, reasoning, and structured-output schema; matching SHA-256 hashes are
  stored in the ledger. Create adds the configured output ceiling,
  `service_tier="default"`, `background=False`, `store=False`, and synchronous
  `stream=False`. These response-only options are audited separately; no tools
  are sent.
- `create_live_client` imports the SDK only when explicitly called, reads
  only `OPENAI_API_KEY`, sets `max_retries=0`, and requires a finite timeout.
  It does not read credential files. Provider exceptions and response text
  are not copied into diagnostics or ledger evidence; metadata is allowlisted.

## Historical initial offline verification checkpoint

- `python3 -m unittest discover -s tests -p 'test_model_budget.py'`: 14 tests,
  passed, exit code 0.
- `python3 -m unittest discover -s tests -p 'test_openai_course_client.py'`:
  25 tests, passed, exit code 0. The suite includes an isolated temporary
  checkout that blocks OpenAI SDK imports, removes the API key, and starts
  without an `out/` directory.
- Exact command output and exit codes are preserved in
  `out/exam/task-014/` and in the Task 014 budget review archive.
- The offline repository checks and tracked-file diff check are recorded in
  the same verification directory. No existing tracked file was modified;
  existing published output and earlier Task 013 evidence are preserved.

These are unit and local repository checks using injected SDK doubles. They do
not establish the installed SDK interface, provider token-count agreement,
provider-side enforcement, successful live requests, or a dollar spending
ceiling. No credentials, network requests, model subprocesses, or SDK
installation were used in Phase A.

## Remaining live checks

All remain **NOT RUN** and belong to later phases:

- Inspect and pin the compatible OpenAI Python SDK, then verify its real
  `responses.input_tokens.count` and `responses.create` interfaces.
- Configure credentials outside project files, select explicit numerical
  run/output/call limits, and verify the exact structured request with the
  live count endpoint.
- Demonstrate bounded live completion and refusal before an unaffordable
  generation dispatch; preserve request, usage, response, and ledger evidence.
- Route normal extraction and actual evaluation through one shared controller
  that reuses the same ledger across checker retries and evaluation cases.
- Verify failure containment and input isolation in that integrated workflow,
  then run actual evaluation only after every later acceptance gate passes.

Actual evaluation remains disabled. The adapter is not connected to the
production runner or evaluation command.


## Failure-containment repair and verification

Further fault tests exposed mutable run limits, interruption paths that did
not block the run, unchecked client retry settings, and an error after usage
settlement that allowed another attempt. Count-response accessors and nested
repair containers also needed stricter handling. The following decisions
complete the offline Phase A repair:

- Expose immutable run limits and bind each reservation to its output cap.
  Interrupted writes block the run; uncertain usage retains its allowance.
  Numeric bound contradictions reported by incomplete responses are retained
  as explicit evidence without releasing that allowance.
- Validate client retry/timeout settings before counting and again afterwards.
  A failed or malformed count abandons the run with no generation charge.
- If response parsing fails after settlement, retain confirmed usage and
  permanently stop. Do not recreate an uncertain reservation for usage that
  has already been validated and settled.
- Check nested repair containers and scalar types before forwarding them.
  Allow only field-shaped response/request/model audit identifiers. Shape
  checks do not authorize callers to supply secrets or reference answers.
- Set default service processing, disable background execution explicitly,
  audit response-only settings separately, and pin the live factory to the
  official API base URL. The API contract is documented in the
  [Responses create reference](https://developers.openai.com/api/reference/cli/resources/responses/methods/create).

Expanded tests against the original code failed: 19 ledger tests produced
8 failures and 1 error, and 37 adapter tests produced 17 failures and 2 errors
(including subtests). After repair, **19 ledger and 37 adapter tests passed**.
All **151 available course/evaluation/budget component tests passed**. The
complete repository suite remains for ordinary WSL; these 151 tests do not
include the existing weather/MCP modules. Original and repaired test output
is retained in the repair package.

The original 39-test checkpoint remains historical evidence. No live API,
SDK installation, credentials or source collection was used in this repair.
No existing tracked code/data or normal outputs were modified. The adapter
remains unwired and actual evaluation stays disabled. Live count agreement,
provider behaviour and integrated invocation-wide enforcement remain later
acceptance gates. Accounting assumes one trusted serial controller, not
arbitrary code attempting to bypass the ledger.

## Completed ordinary-WSL Phase A checkpoint

The ordinary-WSL verification record is preserved in
`out/exam/task-014/wsl-review-rglNnf/verification.log`, with preserved-file
hashes in `out/exam/task-014/wsl-review-rglNnf/preserved-files.sha256`.

- Corpus/reference check passed for nine source cases.
- Offline component replay passed at
  `out/course-evaluations/run-20261107T162557.247516Z-3b26e9fd`.
- Offline probe and checker passed.
- All 188 repository tests passed.
- All seven preserved-file checksums matched.
- Verification exit code: **0**.

This is offline Phase A verification. The adapter remains isolated and
unwired, and actual evaluation remains disabled. SDK installation, live
requests, provider count agreement, and provider enforcement remain
**NOT TESTED**. The initial offline checkpoint and failure-containment repair
record above are historical checkpoints, retained as such.
