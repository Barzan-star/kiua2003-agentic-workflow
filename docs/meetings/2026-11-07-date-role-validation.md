# Date-role validation design session — 2026-11-07

## Problem

The course checker accepted a date when the ISO value appeared in its cited
quotation, even if the source assigned that date to the other field. The
fixture has two relevant layouts: labelled values in section 1 and a
whitespace-flattened table in section 2. In that table, `Oppstartsdato` comes
before `Søknadsfrist`, so relying on a presumed deadline/start ordering would
misread its values.

This session concerns injected checker-validation faults. They are not
observed extraction mistakes, do not constitute a completed model evaluation,
and provide no evidence that faulty dates were published.

## Decisions

- Keep all candidate and source mutations inside deep-copied in-memory test
  data; preserve the checked-in fixture.
- A rejected date must produce an error naming both the course and the
  relevant date field. An unrelated validation error cannot satisfy the test.
- Determine role only from the cited source context. Accept date-only quotes
  when that context explicitly and unambiguously assigns the date to a role.
- For flattened rows, pair date values with the date-role headers in their
  actual column order. Do not infer roles from chronological order.
- Reject a context with multiple distinct values for the requested role when
  no rule selects one. Equal deadline and start dates remain valid when both
  roles are labelled.
- Preserve date normalization and all existing metadata, evidence membership,
  missing-value, fee, prerequisite, and application-status checks.

## Injected cases

The focused suite retains positive controls for the unmodified candidate,
date-only quotations in labelled context, clearly labelled equal dates, and
Norwegian month-name, numeric, and ISO date forms. Negative cases cover:

- Introduction and PLS start dates copied into `application_deadline`;
- an application deadline copied into `start_date`;
- both dates swapped while quoting the entire labelled section;
- removal of only the two role labels while preserving the rest of the
  overview context, including its fee quotation;
- two distinct deadline values in the cited context without a selection rule;
- swapped dates from the actual flattened section-2 table.

The table also has a positive control using its correct dates. Its evidence
uses the section text as the quotation, and the test verifies roles from the
actual `Oppstartsdato` then `Søknadsfrist` headers.

## Observed results

The original focused run (before correcting the regression assertions) is
preserved unchanged in `out/exam/task-012/focused-test-results.txt`: 8 tests,
4 failures, exit code 1 against the original checker SHA-256 recorded in that
file. After correcting the tests, the unchanged checker ran 11 tests and had
7 failing rejection assertions, exit code 1. The positive controls passed.
The complete output and actual exit code are in
`out/exam/task-012/date-role-corrected-before.txt`.

After the checker repair:

| Command | Observed result | Exit code |
| --- | --- | ---: |
| `python3 -m unittest discover -s tests -p 'test_course_date_roles.py'` | 11 tests passed | 0 |
| `python3 -m unittest discover -s tests -p 'test_course*.py'` | 39 tests passed | 0 |
| `git diff --check` | Passed | 0 |

The captured command outputs are in `date-role-after.txt`,
`course-suite-after.txt`, and `diff-check.txt` under
`out/exam/task-012/`. The course suite emits expected stub messages from
workflow tests while still passing. No live collection or model subprocess
was run.

Ordinary-WSL full verification passed: the offline probe and evaluator passed,
the full unit suite ran 84 tests in 4.524 seconds and passed,
`git diff --check` passed, and the protected-path diff check passed. Overall
verification exit code: 0. Complete output:
`out/exam/task-012/full-verification-wsl.txt`.

## Repair

The standard-library checker now parses supported Norwegian and English role
labels in cited source sections. It maps labelled field/value dates and, for a
flattened table, maps the row's date sequence to the role headers in header
order. It rejects missing role support and multiple distinct values for the
requested role with a message that identifies the course and field. Existing
quote membership and other course validations remain active. The implementation
does not use date order, demand distinct deadline/start values, or encode
course-specific dates.

## Additional validation review

Independent verification reproduced the initial 39 passing course tests.
Further candidate/source mutations showed that the first repair could ignore
later table rows, combine a date quotation with role support from a different
citation, or read an unrelated date after an unstated deadline. Another case
showed that an early clear citation could hide a later ambiguous one.

The extended focused suite contains 19 tests. It adds rejection cases for
these gaps and positive controls for duplicate table rows with identical
dates, consistent citations from both layouts, and explicitly labelled inline
dates. An unsupported later table row is also checked so that parsing cannot
silently stop after the first supported offering. Against the first repair,
19 tests ran with 4 failures, exit code 1. The full output and checker hash are
retained in `out/exam/task-012/independent-date-role-before.txt`.

The revised decision is to keep each date-bearing quote and its context
together, require consistent unambiguous support, inspect every supported
table row, and reject unsupported value/row layouts. Role labels are matched
to explicit date cells; a nearby documentation date does not become an
application deadline. This remains a structural validation rule.

The updated checker passed 19 focused tests and 47 course tests in independent
verification under Python 3.12.14, both with exit code 0. The source fixture
remained byte-for-byte unchanged. Separate after-repair outputs are retained
in `independent-date-role-after.txt` and `independent-course-suite-after.txt`.
The original test-first and initial-repair logs remain separate and unchanged.
Ordinary-WSL full verification is recorded above.

## Remaining work and limits

The flattened-table parser is scoped to recognised column headers and rows
with corresponding date cells. Unknown columns, annotated values, or other
serialisations may need more cases and parsing support. These deterministic
tests validate checker behavior, not model extraction accuracy. Report any
later model evaluation separately.
