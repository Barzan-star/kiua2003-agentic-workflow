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
  agreement, and evidence/value support. Unknown fields stay unknown; a
  deadline does not imply open applications.
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

## Architecture and limits

`harness/course_sources.py` owns constrained source collection and filtering.
`harness/run_courses.sh` snapshots one successful collection and orchestrates
the extraction/check/render stages. `harness/course_records.schema.json`
defines the candidate shape; `eval/check_courses.py` checks fields and
quotations against the immutable run input; `harness/render_courses.py`
creates the deterministic local outputs.

Quotation membership and normalization are mechanical evidence checks, not a
semantic proof. They cannot establish that a model included every prerequisite
or retained every important qualification. Human review of source context and
the retained snapshot remains necessary for semantic completeness. Offline
collection does not make the Codex generation stage offline.

## Verification

```sh
bash -n harness/run_courses.sh
./harness/run_courses.sh --offline --dry-run
python3 -m unittest discover -s tests -p 'test_course_records.py'
python3 -m unittest discover -s tests -p 'test_course_workflow.py'
git diff --check
```

The API accepted the schema in WSL run
`out/training/run-20261028T162922Z-UqNKq8`, but its three candidates were
rejected. After the prompt and retry-context repair, all 65 repository tests
passed in ordinary WSL. Actual run
`out/training/run-20261028T165059Z-SOo49E` then passed on extraction attempt 1,
exited 0, and published both outputs. This verifies one working end-to-end
path; it does not establish general extraction accuracy or complete the
planned final-exam evaluation and safety work.
