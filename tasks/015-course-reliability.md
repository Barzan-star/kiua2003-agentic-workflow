# Task 015: Reliable source identity, missing flags, and offering dates

## Goal and measured baseline

Use the completed fixed-set measurement recorded in
`docs/meetings/2026-11-08-measured-course-evaluation.md` as the baseline for a
separately declared reliability improvement. Address three measured defect
classes: candidate source URLs altered from trusted source metadata, a supplied
field also reported missing or uncertain, and a date selected from conflicting
offerings without a defensible selection.

The 2026-11-08 run is a single fixed corpus trial, not an estimate of unseen
course performance. Its retained evidence is under
`out/course-evaluations/run-20261108T155558.513345Z-54fe16fa/`; preservation,
execution, and receipt evidence is under
`out/exam/task-014/measured-evaluation-20261108T153450Z-nu8kg8co/`. Do not
modify, replace, or reinterpret those artifacts as results of this task.

## Observed defects

The following are observations in the retained run and meeting record, not
proposed behavior:

- In S05, the final candidate gives the Robot course a URL containing
  `eleikere` where the retained trusted source URL has `elektrikere`. In S06,
  later candidates also corrupt exact course URLs. The production checker
  rejects the S05 final URL. URLs are outside the 147 scored scalar value
  slots, so the value score does not capture this metadata failure.
- In S03, Robot's `delivery_format` has a source-supported non-null value and
  is also listed in `missing_or_uncertain_fields`. This delivery contradiction
  was scored incorrect and contributes one of the three incorrect values in
  the 144/147 result. Its known module-2 prerequisite is likewise present
  while `prerequisites` is marked missing; that contradiction is outside the
  scalar value slots. The checker accepted both missing-flag contradictions
  in that measured candidate.
- In S05, the Introduction source contains multiple offerings. The final
  candidate assigns 2027-01-03 as the application deadline and 2027-02-09 as
  the start date based on one row, despite no supported selection of that
  offering. Both dates occur in the snapshot; the defect is unsupported row
  selection and precision. Earlier retry behavior corrected then reintroduced
  dates. The final checker rejected the ambiguous roles, and the workflow
  exhausted its three attempts.

These defects are distinct from the measured injection attempt in S06, which
did not induce the targeted fabricated fee or date. That narrow observation is
not a general security claim. Do not describe valid values as invented when
they occur in a source but were assigned to an unsupported offering.

## Proposed solution, to be validated

Keep the source snapshot as the authority for course identity and exact URL.
Prefer having the trusted workflow attach/restore source identity from the
preflighted source bundle, so the model does not author a URL. If the candidate
contract continues to contain a URL, the checker must still require exact
equality with the same course's snapshot URL and reject altered, misspelled,
cross-course, or unapproved URLs. A workflow convenience must not bypass this
independent check.

Make `missing_or_uncertain_fields` mechanically consistent with values in the
same record. Define and document the contract for scalar fields, dates,
planned period, application status, fee, materials qualification, delivery,
and prerequisites. A field with supplied content cannot simultaneously be
marked missing/uncertain; a null/empty field that is genuinely unavailable
must be represented according to the established contract. For list-valued
prerequisites, any supplied supported prerequisite makes the field supplied.
Do not infer that a field is complete merely because a value was emitted:
evidence validation remains required, and this consistency rule does not prove
semantic completeness.

For dates, preserve the existing requirement that date citations support a
consistent deadline/start-date role. Additionally, when source context
contains conflicting offering rows and no explicit supported selection binds
the candidate to one offering, dates that depend on choosing among those rows
must remain unknown. Do not select the first, nearest, earliest, or otherwise
preferred row heuristically. Retain support for unambiguous dates, explicit
field/value labels, and established flattened-table headers where role and
offering association are sufficiently clear. Keep each date quotation paired
with its own context and inspect every row needed by the checker decision.

These are proposed controls. Implementation details may refine them only while
preserving the observable regression requirements below and the established
source, checker, retry, evidence, and rendering contracts.

## Regression cases

Add deterministic offline tests using the real checked-in course fixture and
injected workflow/model doubles where needed. Cover at least:

1. A candidate URL with one misspelling, a URL copied from another approved
   course, and an unapproved URL are rejected or replaced from trusted
   metadata before publication. Assert the final published/run candidate
   carries the exact URL from its own immutable source snapshot. Checker tests
   must independently reject bad URLs when presented directly.
2. A non-null source-supported delivery value plus a missing flag is rejected
   (or consistently normalized before checking, with the checker still able
   to reject contradictory direct input). A supplied prerequisite list plus
   a `prerequisites` missing flag is covered. Include valid null/unknown cases
   and legitimate missing flags to prevent blanket removal of missing
   markers.
3. Two conflicting offering rows with distinct start dates and/or deadlines:
   selecting either row without an explicit supported association is rejected;
   null dates with the appropriate missing flags pass. Test each date role,
   mixed citations, repeated identical rows, and a clearly labelled or
   otherwise unambiguous date so abstention does not disable valid extraction.
4. A repair attempt cannot reintroduce unsupported conflicting-offering dates
   or corrupt trusted URL metadata. Exhausted rejection still cannot publish a
   candidate or overwrite prior normal outputs.
5. Regression controls for established behavior: source membership and exact
   quote checks, date-role agreement, labelled dates, flattened tables,
   genuine unknown values, fee/evidence checks, and renderer behavior remain
   enforced. The production checker must not be weakened or replaced by a
   scorer, prompt instruction, post-hoc score, or model self-report.

Use no personal data. Tests must not require network access, source collection,
provider credentials, or model calls. Do not run tests or model/collection
commands while preparing this specification.

## Implementation scope

Implementation should stay within the existing course workflow and checker
design. Expected paths to consider (final scope to be confirmed before coding):

- `harness/course_workflow.py` and/or the candidate normalization boundary for
  source-derived identity and consistent missing flags;
- `eval/check_courses.py` for independent exact URL, missing-flag consistency,
  and ambiguous-offering validation;
- `tests/test_course_workflow.py`, `tests/test_course_records.py`,
  `tests/test_course_date_roles.py`, and focused new tests if useful;
- `tasks/015-course-reliability.md` and a concise implementation/evidence note
  under `docs/meetings/` if required by the review.

Do not change the frozen course source fixture, frozen evaluation case corpus,
reference answers, historical evaluation results, or the existing measured
run. Reference answers and scorer outputs must remain outside every model
input, prompt, retry feedback message, workflow log sent to the model, and
provider request. Only approved source data, extraction instructions/schema,
and exact production-checker repair feedback may enter model requests. Do not
edit the independent scoring implementation to make the new behavior appear
successful. Any later effectiveness trial is a separately declared run with
new evidence; it must score all planned outcomes, including rejected final
candidates, without success-only selection.

The repository instruction says to ask before editing anything in `eval/`.
Therefore, if implementation requires changes to `eval/check_courses.py`,
obtain that approval before editing it. This specification does not authorize
implementation or edits to `eval/`.

## Evidence preservation and reporting

Before implementation, record hashes or an equivalent protected-file
inventory for the frozen fixtures/reference, historical measured run and
receipts, scorer, model-input construction paths, normal published outputs,
and other protected files chosen for the change. After implementation,
verify unchanged protected items against the recorded inventory. Preserve all
pre-existing `out/` evidence byte-for-byte. Put new verification evidence in a
fresh ignored `out/exam/task-015/` directory; never overwrite an existing
directory or historical result. Record exact commands, outputs, exit codes,
and artifact hashes. Clearly separate deterministic test results from any
future provider-generated evaluation. Do not claim improved model accuracy
from unit tests or checker controls.

## Acceptance commands

Run from the repository root after implementation and approval for any
`eval/` edits. Capture exact output and exit code in the new task evidence
directory. Preserve the repository's required offline probe, repository test,
and whitespace checks, plus the course-specific regression checks:

```sh
python3 harness/probe.py --offline && python3 eval/check_probe.py
python3 -m unittest discover -s tests
python3 -m unittest discover -s tests -p 'test_course_records.py'
python3 -m unittest discover -s tests -p 'test_course_date_roles.py'
python3 -m unittest discover -s tests -p 'test_course_workflow.py'
python3 harness/course_evaluation_cases.py --check
python3 harness/evaluate_courses.py --replay
git diff --check
```

When this specification was first prepared, the acceptance commands above
were **NOT RUN**. That records the specification-only checkpoint. The scoped
checker-consistency implementation and its actual verification are recorded
in `docs/meetings/2026-11-08-course-reliability.md`. The remaining Task 015
workflow, URL-normalization, and further regression work is still pending.
No model call, source collection, staging, commit, or push was performed for
the checker-consistency repair.

## Ordinary-WSL checker-consistency checkpoint

The ordinary-WSL review recorded in
`out/exam/task-015/wsl-review-20261108T184807Z-ef2rh5nm/` passed all eight
verification commands with exit code 0. The repository suite passed 282 tests
with zero skips. Pinned SDK/MCP imports, the course corpus check, offline
component replay, offline probe and checker, whitespace check, and protected-
path check passed. All 321 preservation entries matched, and the review
checked 314 entries from the original protected inventory. Replay passed as
`run-20261108T184809.255040Z-a2c714dd`.

The SDK's HTTP log lines for the `.invalid` endpoint came from a synthetic
in-memory test transport; they were not provider requests. Workflow-side
reliability work and a post-change measured evaluation remain pending. This
checkpoint does not complete Task 015 and makes no claim that model accuracy
improved.
