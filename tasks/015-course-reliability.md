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

## Proposed workflow contract (test-first phase)

1. After validating the exact approved course-ID set, assemble `title`,
   `source_url` and `retrieved_at` from the immutable preflighted source
   snapshot. Never guess, replace or repair course IDs.
2. Preserve each raw model response byte-for-byte separately from the
   assembled candidate. Link raw output, source snapshot and checked candidate
   with hashes and a versioned assembly receipt identifying metadata changes.
3. Preserve every non-metadata value, evidence item and missing flag. Invalid
   facts and contradictions must still be rejected.
4. Checker, renderer and retry feedback must refer consistently to the
   assembled candidate. Keep the preceding rejected candidate aligned with the
   checker feedback supplied on retry.
5. Missing, changed or unwritable required evidence must stop further
   dispatch and block the shared ledger. Evaluation must verify both raw and
   assembled evidence before continuing.
6. Conflicting offerings without a supported selection require abstention for
   affected dates. Identical repeated offerings remain valid. Do not silently
   rewrite model-supplied dates.
7. Retain the current API schema for this phase. Describe metadata assembly
   honestly: the model may still emit metadata, but trusted source metadata
   determines the checked/published record.

### Receipt contract for the test-first phase

Each completed generation must retain its decoded model text verbatim as
UTF-8 bytes in a per-attempt raw-response file. Assembly produces a distinct
candidate file; raw response bytes are never rewritten to make them match the
candidate. A versioned per-attempt receipt links the raw response, immutable
source snapshot, and assembled candidate using SHA-256 hashes computed over
the exact stored bytes. It also records the metadata fields changed for each
course, with the model-emitted and source-snapshot values. Non-metadata facts,
evidence, and missing flags remain byte-equivalent at the JSON-value level.
Retries carry the exact preceding assembled candidate and exact checker
feedback. Evaluation verifies the raw, source, receipt, and candidate links
before it continues to another case; missing, modified, or unwritable required
evidence is an infrastructure failure and blocks the shared ledger.

### Test-first corrections (2026-11-08)

Corrected the initial workflow test draft before production implementation.
Repeated-offering coverage now duplicates only an offering row and has distinct
conflicting-date, explicit-unknown-with-required-flags, and identical-row
controls. The simulated SDK supplies three generation responses per rejection
scenario and tracks count and generation requests separately; each scenario
uses fresh evidence and ledger files. Metadata assembly checks use malformed
IDs through the shared workflow, require one generation for metadata-only
correction, preserve all non-metadata values, and require a versioned receipt
with raw/source/candidate hashes and metadata changes. Retry assertions bind
the exact prior candidate and checker feedback. Fault injection covers
evidence-write failure and evaluator evidence integrity; publication checks
run the normal CLI with injected collection/provider doubles and compare the
actual JSON and Markdown publication targets byte-for-byte after rejection.
No production implementation was changed for this correction. The captured
test results and production-file hashes are in the new correction evidence
directory under `out/exam/task-015/`.

### Reviewed workflow regression baseline (2026-11-08)

The initial corrected draft reported nine tests with four failures. Further
review found that its evaluator test blocked the ledger in test code, its
conflicting-date quotation omitted the newly added row, and its retry did not
change metadata. Those passing checks did not establish the corresponding
workflow contracts. The original test logs remain historical evidence.

The revised tests invoke the real injected evaluator and require it to block
the shared ledger automatically after missing or changed raw/assembly
evidence. A clean seven-case injected execution is the positive control;
existing candidate-tamper detection is also retained as a passing control.
Retry tests now include both wrong course metadata and a wrong fee, and check
the exact assembled candidate, checker feedback and request hashes. Faults
inserted after checker receipt persistence must stop before the next token
count request. Raw evidence includes leading/trailing whitespace. Publication
tests redirect all CLI output into temporary storage that is cleaned up.

The reviewed baseline ran in an isolated source copy with production hashes
matching the uploaded checkpoint: 18 tests, seven passing controls and 11
expected assertion failures, zero test errors or skips, exit code 1. These
failures expose absent metadata assembly, raw/assembly receipt persistence,
and required integrity checks before retry or the next evaluation case. They
are not model-performance measurements. The 25 runtime/fixture file hashes
checked in that isolated copy were unchanged. Ordinary-WSL reproduction is
required before implementation; the repair helper records its own result in
a fresh ignored evidence directory. No production implementation is included
in this test-only update.

Receipt version 1 uses per-attempt `raw-response-N.txt`, `assembly-N.json`
and `candidate-N.json`. The receipt records `version`, `raw_sha256`,
`source_sha256`, `candidate_sha256` and `metadata_changes`; each change
contains `course_id`, `field`, `model_value` and `source_value`. Only title,
source URL and retrieval timestamp may be assembled. Invalid course-ID sets
remain unchanged and checker-rejected; assembly must not manufacture IDs or
records. Keep the raw output and record the skipped assembly decision for
those attempts. Preserve all other JSON values, evidence and flags.

Hash links must bind the receipt as well as its referenced artifacts and
verify that the assembled values match the raw candidate plus exactly the
allowed trusted metadata changes. Missing, modified, malformed or unwritable
required evidence blocks continuation. The raw text is retained before
interpretation. The checker, renderer, repair input and current evaluation
score all use the same assembled candidate. Historical evaluation artifacts
and results are not regenerated or relabelled.

### Workflow repair implementation (2026-11-08)

The shared controller now validates course IDs as a complete unique set
before applying trusted metadata by ID. It retains decoded output verbatim,
records per-attempt raw/candidate/assembly evidence, and sends the assembled
candidate through checker, renderer, and repair flow. Actual evaluation shares
the assembly evidence verifier and verifies completed-case links before
scoring or proceeding. Invalid ID sets remain unchanged for independent
checker rejection. Deterministic tests and replay exercise this behavior; they
are workflow checks, not a model-accuracy measurement. Historical evaluation
artifacts and reference expectations were not changed.

### Workflow integrity integration (2026-11-10)

Integrated the exact controller/evaluator repair verified by the ordinary-WSL
source-copy review in
`out/exam/task-015/current-repair-review-20261110T100601Z-5100cc1c/`.
Completed-attempt verification is shared across retry, acceptance, rejection
and evaluation boundaries. It binds source/request identity, raw and assembled
evidence, checker feedback and budget receipts to the caller-owned ledger.
Boolean assembly versions are rejected. The original 18 metadata tests are
unchanged; 13 evidence-integrity regressions were added in
`tests/test_course_workflow_integrity.py`.

The actual working repository passed 313 tests with zero failures, errors or
skips, and corpus validation passed. Integration evidence and byte-preserving
backups are in `out/exam/task-015/integration-20261110T130716Z-7778ac8c/`.
The approved source-copy review also passed the offline probe/check, replay,
runner syntax/previews and patch checks. Existing protected inputs and prior
outputs were checked against the integration inventory.

These checks establish deterministic integrity behavior. A separately declared
post-change provider evaluation, qualitative review and remaining exam stress
work are still pending. Historical Task 014 measurements remain unchanged.
