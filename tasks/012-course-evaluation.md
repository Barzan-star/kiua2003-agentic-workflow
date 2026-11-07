# Task 012: Course evaluation and date-role validation

## Problem

The course checker previously verified that a claimed date appeared in its
quotation, but not that the cited context assigned it the claimed role. A
genuine start date could therefore pass as an application deadline, and vice
versa. The checked-in source snapshot provides labelled field/value dates in
section 1 and a flattened table in section 2. The table headers place
`Oppstartsdato` before `Søknadsfrist`.

## Repair

`eval/check_courses.py` now checks each non-null date against role assignments
in its cited source section. It accepts date-only quotations when section
context supplies one unambiguous role/value, reads the labelled field/value
layout, and maps dates in the flattened row according to the order of its date
column headers. If the requested role is unsupported or has multiple distinct
values in a cited context, the checker rejects it with an error naming the
course and field. It does not use date order, require the dates to differ, or
hardcode course dates. Existing quotation membership, metadata, missing-value,
fee, prerequisite, and application-status checks remain in place. Norwegian
month names, numeric dates, and ISO dates remain supported.

## Regression cases and observed results

The tests use the saved fixture as read-only input and deep-copy candidate and
source variants in memory. They cover correct records and date-only quotes in
labelled context, Introduction and PLS start dates misreported as deadlines,
a deadline misreported as a start date, swapped values in a fully quoted
labelled section, an unlabelled context, two distinct values for one role,
equal but explicitly labelled deadline/start values, supported date formats,
and correct/swapped dates in the actual flattened section-2 table. Rejection
assertions require an error naming the relevant course and field. The
ambiguous-context case removes only the two role labels and preserves the
remainder of the overview text, including its fee quotation. The saved fixture
was not edited.

The original focused test-first result is retained unchanged in
`out/exam/task-012/focused-test-results.txt`: 8 tests ran and 4 failed against
the unchanged checker. After correcting the regression tests, the unchanged
checker ran 11 tests with 7 failures; that complete run and exit code 1 are in
`out/exam/task-012/date-role-corrected-before.txt`. The failures were the
injected wrong-role or ambiguous-role cases; the positive controls passed.

After repair:

- `python3 -m unittest discover -s tests -p 'test_course_date_roles.py'` ran
  11 tests and passed (exit code 0).
- `python3 -m unittest discover -s tests -p 'test_course*.py'` ran 39 tests
  and passed (exit code 0).
- `git diff --check` passed (exit code 0).

Ordinary-WSL full verification passed: the offline probe and evaluator passed,
the full unit suite ran 84 tests in 4.524 seconds and passed,
`git diff --check` passed, and the protected-path diff check passed. Overall
verification exit code: 0. The complete output is in
`out/exam/task-012/full-verification-wsl.txt`.

Complete outputs and actual exit codes are retained in
`out/exam/task-012/date-role-after.txt`,
`out/exam/task-012/course-suite-after.txt`, and
`out/exam/task-012/diff-check.txt`. No live collection or model subprocess was
run.

These are deliberately injected validation faults, not observed model
mistakes. This work tests checker behavior; it is not a completed model
evaluation and does not establish that faulty dates were published.

## Additional review and repair

The initial 11 focused tests and 39 course tests also passed during independent
verification. Additional injected cases exposed three gaps in that first
repair: only the first table row was inspected; a date quotation could borrow
role support from a different citation; and a role label could collect an
unrelated date later in prose. A clear citation could also hide an ambiguous
date-bearing citation through early acceptance.

Eight additional tests extend the focused suite to 19. They cover different
dates in multiple table rows, repeated rows with identical dates, an
unsupported later row, mismatched quote/context pairs, consistent citations
from both layouts, an unstated deadline followed by a documentation date,
explicit inline labels, and a clear citation combined with an ambiguous one.
Against the first repair, 19 tests ran with 4 failing rejection cases. These
results and the first repair's checker hash are retained in
`out/exam/task-012/independent-date-role-before.txt`.

The checker now pairs each quotation with its own source section. Every
date-bearing citation must support the requested role unambiguously; a
different citation cannot supply missing support or override ambiguity.
Explicit date cells are parsed beside labels or immediately after standalone
labels. The table reader inspects all rows in the supported block, retains
distinct role values, and rejects unsupported row layouts. It never selects
the first offering implicitly. Identical repeated dates remain valid.

Independent verification used Python 3.12.14:

- Focused date-role tests: 19 passed, exit code 0.
- All course tests: 47 passed, exit code 0.
- The source fixture's bytes remained unchanged.

Complete outputs are in `independent-date-role-after.txt` and
`independent-course-suite-after.txt` under `out/exam/task-012/`. These results
are separate from the initial repair logs. Ordinary-WSL full verification is
recorded above.

## Remaining work and limits

The table reader supports the fixture's flattened representation: recognised
column headers followed by rows containing the corresponding date cells. Its
column vocabulary and explicit date-cell grammar are intentionally limited.
Unknown table columns, annotations, or prose layouts may require additional
parsing and regression cases. The checker does not establish broader semantic
completeness of course extraction. Any later model evaluation must be reported
separately from these deterministic injected-fault tests.
