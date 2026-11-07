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
industrial companies in Gjøvik and Toten. This is a design target; direct
interviews or validation of employer demand have not been performed.

## Definition of success

- One command (`./harness/run_courses.sh --offline`) runs the existing source
  collector, snapshots its output under ignored `out/training/run-*`, performs
  structured extraction, checks the candidate against that snapshot, and
  publishes validated JSON plus a deterministic Norwegian Markdown report.
- Normal mode uses the collector's existing constrained live collection;
  `--offline` uses its checked-in fixture. `--dry-run` has no side effects.
- Records contain course ID, title, exact URL and retrieval timestamp,
  application deadline, exact start date, distinct planned period,
  prerequisites, delivery format, NOK study fee and materials qualification,
  application status, explicit missing/uncertain fields, and section-indexed
  verbatim evidence for each extracted fact.
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
- Codex extraction uses a fresh candidate each time and runs at most three
  times. Only checker content rejection is retried with the exact feedback
  and the preceding rejected JSON. The agent sees explicit section indices;
  textual values are copied from source quotations and unknown-field flags
  follow the documented checker contract.
  Failed candidates never publish, and old candidate files cannot satisfy a
  missing output.
- JSON and Markdown publication is local. Markdown is rendered from validated
  records without another model call and includes source links, retrieval
  times, and uncertainty.
- Deterministic tests use the real checked-in course fixture and stubs for
  Codex and external workflow processes. No live fetch or model call is part
  of these checks.
- Task 013 Phase B adds a standard-library-only offline component replay for
  fixed source and candidate-mutation controls. It scores against the reviewed
  reference independently of the production checker, keeps provenance groups
  separate, and reports fixed-denominator value and text coverage. It does
  not estimate model accuracy or instruction-resistance performance.

## Architecture and limits

`harness/course_sources.py` owns constrained source collection and filtering.
`harness/run_courses.sh` snapshots one successful collection and orchestrates
the extraction/check/render stages. `harness/course_records.schema.json`
defines the candidate shape; `eval/check_courses.py` checks fields and
quotations against the immutable run input; `harness/render_courses.py`
creates the deterministic local outputs.

Quotation membership, normalization, and date-role checks are mechanical
evidence checks, not a complete semantic proof. Explicit labels and table
headers support the date-role decision, but the checker cannot establish that
a model included every prerequisite or retained every important
qualification. Human review of source context and the retained snapshot
remains necessary for semantic completeness. Offline collection does not make
the Codex generation stage offline.

## Verification

```sh
bash -n harness/run_courses.sh
./harness/run_courses.sh --offline --dry-run
python3 -m unittest discover -s tests -p 'test_course_records.py'
python3 -m unittest discover -s tests -p 'test_course_workflow.py'
python3 harness/course_evaluation_cases.py --check
python3 -m unittest discover -s tests -p 'test_course_evaluation.py'
python3 harness/evaluate_courses.py --replay
git diff --check
git diff --cached --check
```

Task 013 replay output is retained under ignored `out/course-evaluations/`.
The `--actual` option remains disabled before any subprocess or network
dispatch; the replay candidates are synthetic controls only. Candidate
qualitative review and real-model budget enforcement remain future work.

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
