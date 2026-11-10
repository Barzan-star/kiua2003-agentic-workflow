# Specification

## Problem

The project targets the recurring work of comparing published training options
for electricians at small industrial companies in Gjøvik and Toten. Group 2
scopes the first workflow to exactly three Fagskolen Innlandet automation
courses at Raufoss. Course pages can change, repeat section
labels, omit facts, and contain untrusted text. The workflow must preserve the
actual input for each run and must not turn missing information into invented
dates, fees, prerequisites, or application availability.

## Users

Managers responsible for arranging further training for electricians at small
industrial companies in Gjøvik and Toten. The accepted Compulsory 2 report
supports the regional need with the public NHO Innlandet competence survey.
The agreed project scope uses public course data and documentary evidence;
it does not include interviews.

## Definition of success

- One command (`./harness/run_courses.sh --offline` with explicit model
  limits) runs the existing source collector, snapshots its output under
  ignored `out/training/run-*`, performs structured extraction through the
  budgeted Responses API controller, checks the candidate against that
  snapshot, and publishes validated JSON plus a deterministic Norwegian
  Markdown report.
- Normal mode uses the collector's existing constrained live collection;
  `--offline` uses its checked-in fixture. `--dry-run` has no side effects.
- Records contain course ID, title, exact URL and retrieval timestamp,
  application deadline, exact start date, distinct planned period,
  prerequisites, delivery format, NOK study fee and materials qualification,
  application status, explicit missing/uncertain fields, and section-indexed
  verbatim evidence for each extracted fact.
- The planned period is a separately published approximation, not a repeated
  exact date. The checker rejects supported full-date syntax in its value;
  unrelated full dates in the evidence quote do not invalidate an approximate
  value. The prompt forbids deriving a period by truncating an exact date.
  This limited precision check does not prove semantic completeness.
- A standard-library checker enforces types, valid dates and fees, exactly the
  approved course set, same-course source membership, normalized date and fee
  agreement, and evidence/value support. For non-null dates it also verifies
  that cited source context supports the requested application-deadline or
  start-date role, using explicit field/value labels or flattened-table date
  headers. Unsupported or ambiguous role assignments are rejected with the
  course and field identified. Unknown fields stay unknown; a deadline does
  not imply open applications.
- Keep each date-bearing quotation paired with its own cited context. Require
  consistent role support across date-bearing citations, inspect all rows in
  a supported flattened table, and reject unsupported labelled values or
  table rows rather than guessing a role or selecting an offering implicitly.
- Model extraction uses a fresh candidate each time and runs at most three
  times within one caller-owned invocation ledger. Only a completed checker
  rejection is retried with the exact feedback and preceding rejected JSON.
  The model receives only approved source data, the existing extraction
  instructions/schema, and production-checker repair feedback. Textual values
  are copied from source quotations and unknown-field flags follow the
  documented checker contract.
  Failed candidates never publish, and old candidate files cannot satisfy a
  missing output.
- JSON and Markdown publication is local. Markdown is rendered from validated
  records without another model call and includes source links, retrieval
  times, and uncertainty.
  Table cells normalize display whitespace and escape backslashes and pipes;
  the structured records and evidence retain their original content.
- Deterministic tests use the real checked-in course fixture, real ledger and
  adapter, injected SDK doubles, and offline component subprocesses. No live
  fetch or model call is part of these checks.
- Task 013 Phase B adds a standard-library-only offline component replay for
  fixed source and candidate-mutation controls. It scores against the reviewed
  reference independently of the production checker, keeps provenance groups
  separate, and reports fixed-denominator value and text coverage. It does
  not estimate model accuracy or instruction-resistance performance.
- Task 014 Phase C2 adds an explicitly approved actual evaluation path through
  the shared budgeted controller. It preflights the complete fixed corpus,
  shares one client and one token ledger across all approved cases and retries,
  and independently scores each last completed candidate without feeding
  scores back into generation.

## Architecture and limits

`harness/course_sources.py` owns constrained source collection and filtering.
`harness/run_courses.sh` is a repository-root-aware wrapper around
`harness/course_workflow.py`. The normal CLI owns one ledger for its run; the
shared function accepts a caller-owned ledger and injected SDK client so a
later evaluation caller can share one budget across cases. The controller
does not publish normal outputs. `harness/course_records.schema.json` defines
the candidate shape; `eval/check_courses.py` checks fields and quotations
against the immutable run input; `harness/render_courses.py` creates the
deterministic local outputs.

The workflow preserves decoded model text verbatim in a per-attempt raw
response file, then assembles trusted course title, URL, and retrieval time
from the preflighted source snapshot by course ID. The checker, renderer, and
repair input use the assembled candidate. Versioned receipts bind raw, source,
and assembled-candidate hashes and describe the permitted metadata changes.
Actual evaluation verifies this evidence before scoring the assembled output
or continuing to another case. These deterministic checks establish workflow
behavior, not model accuracy; raw model output remains separately inspectable.

Quotation membership, normalization, and date-role checks are mechanical
evidence checks, not a complete semantic proof. Explicit labels and table
headers support the date-role decision, but the checker cannot establish that
a model included every prerequisite or retained every important
qualification. Human review of source context and the retained snapshot
remains necessary for semantic completeness. Offline collection does not make
model extraction offline. The normal CLI requires explicit positive integer
run-token, output-token, and model-call limits, plus `OPENAI_API_KEY`; dry-run
requires neither and creates no files. Successful rendered outputs are kept
in run evidence before the two normal output files are replaced separately.
That pair of replacements is not an atomic transaction.

Storage/context failures, unexpected component errors, and interruption
permanently block the caller-owned ledger before an abandoned case returns.
Missing renderer evidence cannot produce an accepted outcome. Final error
receipts are attempted separately and may be unavailable under a storage
failure; their absence never reopens model dispatch. Invalid source data is
reported separately from infrastructure failure. The CLI returns 130 for
interrupted extraction/checking/rendering and sanitizes unexpected errors.

## Verification

The repository also reproduces the accepted input/dependency study with
`python3 harness/stress_courses.py --offline`. It regenerates frozen source
variants and replays hash-bound retained candidates through the real workflow
using an in-memory provider double. Historical checker code is experiment
data. It needs no Git history, model SDK or old run directories, and preserves
normal publication. These controls are separate from model accuracy.

Current evidence and operating boundaries are recorded in
`docs/exam/evaluation-2026-11-10.md`,
`docs/exam/stress-study-2026-11-10.md` and `docs/safe-operation.md`.

```sh
bash -n harness/run_courses.sh
./harness/run_courses.sh --offline --dry-run
./harness/run_courses.sh --dry-run
.venv/bin/python -m unittest discover -s tests -p 'test_budgeted_course_workflow.py'
.venv/bin/python -m unittest discover -s tests -p 'test_course_workflow.py'
python3 harness/course_evaluation_cases.py --check
python3 harness/evaluate_courses.py --replay
git diff --check
```

Task 013 replay output is retained under ignored `out/course-evaluations/`.
Replay remains the default and does not construct a model client. Actual mode
requires `--actual --approve-model-calls` and explicit positive integer
`--run-token-limit`, `--max-output-tokens`, and `--max-model-calls` options;
replay rejects these approval and budget options. The limits are caller
choices, and the project has not selected final measured-run limits. An actual
run uses the frozen source corpus without collecting sources, but model
generation still sends approved source text to the service.

The nine source cases are all preflighted before provider dispatch. Seven are
approved and run in catalog order through `course_workflow.run_course_workflow`
with the same client and ledger. Two preflight rejections make zero count or
generation requests. Candidate mutations remain offline replay controls.
Scoring accepts `current_model` only in explicit actual mode; default replay
continues to accept only its established provenance classes. Complete means
all nine outcomes and required artifacts were finalized with integrity
preserved, not that all extractions were correct. The report retains planned,
scored, unscorable, and not-scored counts against 147 value slots, 119
required-text atoms, and 77 prerequisite atoms. Qualitative review remains
pending.

Completed-case evidence is verified before another case can dispatch. Missing
or changed candidate/checker/render/result receipts abandon the invocation.
A pass-through request audit delegates to the same native SDK client; count
requests and returned responses are tracked independently of reservations.
Reports distinguish actual generation invocations from conservatively used
model-call slots. The first failure is retained alongside later cleanup/report
failures, and the final result receipt is committed after its manifest.

The actual interface has only been exercised with injected SDK doubles in
Phase C2. Such reports use `execution_kind=injected_test` and
`not_model_accuracy=true`; they do not claim provider-generated answers.

The first fixed-set provider measurement completed on 2026-11-08 using the
predeclared limits and frozen sources. All seven approved cases were scored:
144/147 declared value slots were correct, required-text coverage was 119/119,
and prerequisite coverage was 77/77. Workflow acceptance was 5/7 after retries;
the two rejected final candidates remain included in scoring. These counts
describe this fixed set only and do not estimate performance on unseen courses.
The source-grounded case analysis, operational accounting, and coverage limits
are recorded in
`docs/meetings/2026-11-08-measured-course-evaluation.md`. The evaluation does
not complete the exam; student qualitative confirmation, the live normal
workflow, stress study, and final delivery remain pending.

At the initial Phase B checkpoint, the corpus check passed all nine source
cases, the focused suite passed 15 tests with no skips, and replay reported a
pass in
`out/course-evaluations/run-20261107T125143.482270Z-12102324`. The replay
matched all nine source preflight expectations and all nine mutation checker
expectations; protected input and published-output hashes remained unchanged.
The complete repository suite is deferred to ordinary WSL after review.

The API accepted the schema in WSL run
`out/training/run-20261028T162922Z-UqNKq8`, but its three candidates were
rejected. After the prompt and retry-context repair, all 65 repository tests
passed in ordinary WSL. Actual run
`out/training/run-20261028T165059Z-SOo49E` then passed on extraction attempt 1,
exited 0, and published both outputs. This verifies one working end-to-end
path; it does not establish general extraction accuracy or complete the
planned final-exam evaluation and safety work.


## Phase B scoring-control review

Replay success also requires every fixed per-fact scoring expectation: seven
positive controls and nine mutation controls. Checker verdicts alone cannot
establish scorer sensitivity. Missing case results or unexpected value/text
scores fail the replay. Controls retain their original reference facts and
source quotations; production code and Phase A data are unchanged.

Report version 2 records explicit failure manifests, partial case evidence,
planned/unscored denominators, bounded local component dispatch, and before/
after hashes of the relevant source, reference, catalog, implementation,
prompt, schema, and runner files. Output directories cannot resolve into
normal training outputs or outside the repository's `out/`.

The repaired corpus check, 27 focused Phase B tests, and the available
95 course-component tests passed. Replay `out/course-evaluations/run-20261107T131903.943969Z-e94cbd5d`
passed 7/7 positive and 9/9 mutation scoring controls as well as the source,
checker, renderer, and integrity checks. These are synthetic component
results. The complete ordinary-WSL verification is recorded below; this
earlier replay remains an earlier checkpoint.

## Completed ordinary-WSL Phase B verification — 2026-11-07

- Corpus/reference validation passed for all nine source cases. The completed
  offline replay passed with all nine source preflight expectations matched:
  seven accepted cases and two expected source rejections. The five expected
  checker-rejection mutations and four checker-pass sensitivity mutations
  matched, and all four checker-pass mutations rendered without failure.
- All seven positive and nine mutation scoring controls matched. Positive
  `synthetic_reference` controls scored 147/147 value slots, 119/119
  required-text atoms, and 77/77 prerequisite atoms. The `mutated_candidate`
  group scored 180 correct, 2 missing, and 7 incorrect value slots of 189;
  it covered 143/153 required-text atoms and 90/99 prerequisite atoms.
  Replay integrity passed. These are synthetic component results, not model
  accuracy or instruction-resistance performance.
- The offline probe and checker passed, and all 132 repository tests passed
  with no skips. All six source, reference, and published-output checksum
  checks passed. Whitespace and protected-path diff checks passed.
- Verification evidence:
  `out/exam/task-013/wsl-phase-b-rW0DJI/verification.log`.
  Replay evidence:
  `out/course-evaluations/run-20261107T133047.144244Z-3671390d/results.json`.
- Candidate qualitative review, budget enforcement, and actual model
  evaluation remain future work. No model evaluation or source collection was
  performed in this verification.
