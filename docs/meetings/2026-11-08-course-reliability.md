# Task 015 checker-consistency repair

**Date:** 2026-11-08
**Scope:** checker consistency for `missing_or_uncertain_fields` only
**Baseline:** branch `exam/course-reliability`, HEAD
`fec7677070bffb35a56a9338d9940566db286acd`; index empty.

## Contract implemented

The production checker now accepts only these names in
`missing_or_uncertain_fields`: `application_deadline`, `start_date`,
`planned_period`, `prerequisites`, `delivery_format`, `study_fee_nok`,
`materials_qualification`, and `application_status`.

A supplied date, planned period, delivery format, materials qualification,
fee amount, nonempty prerequisite list, or known application status cannot
also be marked missing or uncertain. Zero is a supplied fee amount. Null date,
period, text, and fee values, an empty prerequisite list, and `not_stated` or
`uncertain` application status retain the required missing flag. These rules
check consistency only; they do not establish that a supplied value is
semantically complete or source-correct. Existing type, URL, evidence,
quotation, fee, and date-role checks remain in place. Contradictions are
rejected with course and field details; the checker does not silently edit
values or flags.

## Test-first evidence

The focused suite was expanded before checker implementation. The unchanged
checker ran:

```text
.venv/bin/python -m unittest discover -s tests -p 'test_course_reliability.py'
```

It ran 13 test methods and reported 11 assertion failures, including eight
supplied-value subtest failures. The supplied-value subtests, unsupported
missing-field name, and delivery/prerequisite contradiction controls all
received no checker errors. URL validation, valid unknown values, conflicting
offering dates, unambiguous dates, and repeated identical offering controls
passed. This isolates the missing-flag gaps from unrelated evidence/setup
errors. Complete output and exit code 1 are preserved in
`out/exam/task-015/checker-consistency-20261108T220000Z/pre-repair-focused.log`
and `pre-repair-focused.exit-code`.

## Verification after repair

The requested focused commands were run after the checker change. Exact
commands, complete output logs, and exit codes are retained in
`out/exam/task-015/checker-consistency-20261108T220000Z/`.

| Command | Result |
|---|---|
| `.venv/bin/python -m unittest discover -s tests -p test_course_reliability.py` | PASS, 13 tests, exit 0 |
| `.venv/bin/python -m unittest discover -s tests -p test_course_records.py` | PASS, 10 tests, exit 0 |
| `.venv/bin/python -m unittest discover -s tests -p test_course_date_roles.py` | PASS, 19 tests, exit 0 |
| `.venv/bin/python harness/course_evaluation_cases.py --check` | PASS, nine source cases, base SHA-256 `1ff359c0251075a2274fb037c8c478d4d5ded1e12cf709be5feb0831222a4546`, exit 0 |
| `.venv/bin/python harness/evaluate_courses.py --replay` | PASS, offline component replay `run-20261108T182646.909575Z-03748caf`, exit 0 |
| `git diff --check` | PASS, exit 0 |

The replay is the existing deterministic component/scoring-control replay; it
does not call a model and is not evidence of model accuracy or of improved
course extraction accuracy. The full repository suite remains for ordinary
WSL review.

## Preservation

Before implementation, SHA-256 values were recorded for 317 protected files
in `preserved-before.json`, including every tracked file outside the scoped
checker change, the measured Task 014 run and receipts, frozen source/reference
and evaluation data, prior Task 015 test-first evidence, and normal training
outputs. The post-change comparison checked 315 unaffected files; there were
zero mismatches. The two excluded paths were the Task 015 specification and
test file, which are intentionally edited by this task. The checker is the
authorized implementation target. No frozen fixture, reference, scorer,
historical evaluation result, model request, workflow code, or published
normal output was changed. The full comparison is in `preserved-after.json`.

The original Task 015 test-first evidence remains in the parent
`out/exam/task-015/` directory. New evidence was written to a fresh ignored
directory and did not replace it. No model call, source collection, package
installation, staging, commit, or push occurred.

## Remaining Task 015 work

This repair addresses missing-flag consistency only. The existing checker
continues to enforce exact own-course source URLs and reject unsupported
conflicting-offering date roles, as covered by the reliability/date-role
tests. Workflow-side source-identity normalization, any further offering
association design, additional workflow regressions, and the remaining Task
015 acceptance review are pending. No change to frozen data or the independent
scorer is proposed here.

## Integration regression review

Two older injected-evaluation tests constructed a supposedly checker-accepted
candidate by supplying a delivery value and marking that field missing. The
stricter checker correctly rejects that candidate, causing retries that consume
the injected response sequence and invalidate the tests' original expectations.
Both failures were reproduced before the test-control update.

The two controls now use the source-grounded fragment `nettbaserte samlinger`,
which omits the physical part of the published hybrid delivery. The production
checker accepts its quotation membership, while the unchanged independent
scorer identifies the incomplete delivery value. Explicit precondition checks
confirm checker acceptance before the injected evaluation. The original
acceptance, attempt-count, incomplete-prerequisite, missing-deadline and
quantitative Markdown assertions remain enforced.

A separate regression retains the original missing-flag contradiction: the
production checker must reject it, and independent actual-mode scoring must
still classify its delivery slot as incorrect without modifying the candidate.
This preserves the distinction between checker rejection and scoreability.

In an isolated review checkout, all 263 SDK-independent repository tests passed,
all 39 injected actual-evaluation tests passed, and offline replay passed. The
pinned SDK and MCP suites were not run in that environment; complete
ordinary-WSL verification remains pending. No provider request was dispatched.
Production checker, workflow, scorer, frozen corpus/reference and historical
measurement evidence were not changed by this integration-test update.

## Ordinary-WSL verification checkpoint

The ordinary-WSL review in
`out/exam/task-015/wsl-review-20261108T184807Z-ef2rh5nm/` passed all eight
commands with exit code 0. The full repository suite passed 282 tests with
zero skips. Pinned SDK/MCP imports, the course corpus check, offline replay,
offline probe and checker, whitespace check, and protected-path check passed.
All 321 preservation entries matched; 314 original protected-inventory
entries were checked. Offline component replay passed as
`run-20261108T184809.255040Z-a2c714dd`.

The SDK `.invalid` HTTP log output was produced through a synthetic
in-memory transport and did not represent provider requests. Workflow-side
reliability work and a post-change measured evaluation remain pending. This
checkpoint does not mark Task 015 complete and does not show improved model
accuracy.
