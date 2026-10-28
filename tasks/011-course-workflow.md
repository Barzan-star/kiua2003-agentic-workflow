# Task 011: Compulsory 2 course workflow

## Goal

Complete the walking skeleton for a local, source-linked comparison of exactly
the three approved Fagskolen Innlandet automation courses. The one-command
workflow collects course sources, preserves an immutable run snapshot, asks a
non-interactive Codex agent for structured records, checks those records against
the snapshot, then publishes deterministic JSON and Norwegian Markdown.

## Requirements

- Provide `./harness/run_courses.sh [--offline] [--dry-run]`.
- Run the existing course collector, copy its validated input into a unique
  ignored `out/training/run-*` directory, and never modify the checked-in
  fixture, collector, weather workflow, existing evaluators, permission
  profiles, or dependency files.
- Use `timeout --kill-after=5s 90s codex exec` with strict/ephemeral JSON mode,
  `gpt-6-luna`, low reasoning, `course_summary` permissions, no approvals, no
  web search, agents disabled, the checked-in output schema, and a fresh
  candidate path. Source text is untrusted task data; the prompt must forbid
  obeying source instructions, network access, file edits, and delegation.
- Allow at most three attempts. Retry only candidate content rejection and
  pass complete checker feedback. Model, timeout, absent output, or checker
  infrastructure errors stop immediately. Keep candidates and logs under
  ignored `out/`; only validated records may replace published output.
- Define a JSON schema for exact course metadata, deadline, exact start date,
  distinct planned period, prerequisites, delivery, NOK fee and materials
  qualification, application status, explicit missing/uncertain fields, and
  per-fact evidence with source section index/ID and verbatim quotation.
- The standard-library checker validates required fields/types, dates, fee
  values, unique IDs and the exact course set; verifies metadata and evidence
  against the actual same-course snapshot; checks normalized date and fee
  values against quotations; and rejects unsupported or cross-course facts.
  Unknown values remain unknown. It does not infer availability from deadlines.
- Render `out/training/courses.json` and `out/training/comparison.md` only from
  validated records. Markdown is deterministic, Norwegian-labelled, source
  linked, and identifies source retrieval times and uncertainty.
- Document that mechanical source/evidence matching cannot establish semantic
  completeness, especially for prerequisites and fee qualifications.
- Add deterministic tests for real fixture records, missing values, bad dates
  and fees, forged and cross-course evidence, and workflow failures/publication.
  Stub Codex and external processes; do not invoke a real model or fetch pages.
- Preserve W43 documentation and material.

## Implementation steps

1. Inspect the collector, fixture, weather runner/checker/tests, project docs,
   ignored-output rules, and active Codex permission profile.
2. Write this task specification before implementation.
3. Add the extraction prompt and JSON Schema; choose a field/evidence structure
   that handles duplicate labels by section index.
4. Implement the source-bound standard-library checker and deterministic
   Markdown renderer.
5. Implement the runner with dry-run, offline/live collector invocation,
   immutable source snapshots, strict Codex settings, bounded validation-only
   retries, and publish-after-pass behavior.
6. Add checker and workflow tests using fixtures and stubs only.
7. Update README.md and SPEC.md with architecture, commands, success criteria,
   limitations, and the distinction between offline collection and model use.
8. Run the requested deterministic checks and inspect the final diff/status.

## Acceptance checks

```sh
bash -n harness/run_courses.sh
./harness/run_courses.sh --offline --dry-run
python3 -m unittest discover -s tests -p 'test_course_records.py'
python3 -m unittest discover -s tests -p 'test_course_workflow.py'
git diff --check
```

The implementation checks above use stubs and do not call a real model or
fetch live pages. Subsequent real-run outcomes are recorded below.

## Observed API schema failure

Two real runs failed before extraction with HTTP 400 `invalid_json_schema`.
`out/training/run-20261028T160124Z-FiDGd2` reported that `uri` was not a valid
format in `properties/source_url`. The later run
`out/training/run-20261028T162223Z-i0aCZn` reported that `uniqueItems` is not
permitted in `properties/missing_or_uncertain_fields`. Both run directories
and their event logs are preserved. The API-facing schema now uses only the
permitted conservative keywords; Python retains the removed validation
constraints, including exact course count and uniqueness. The later WSL run
below confirmed API acceptance of that schema.

## Observed extraction failure and context repair — 2026-10-28

`out/training/run-20261028T162922Z-UqNKq8` reached real model extraction, but
all three candidates were rejected. Attempt 1 contained unsupported textual
paraphrases; attempt 2 retained an out-of-range evidence index; attempt 3
omitted `planned_period` and `application_status` flags for both of the first
two courses. No candidate was published. The full project suite had passed
60 tests before the schema and later context repairs; that historical result
is not a full-suite result for the latest files.

Inspection of the actual files showed that the prompt did not state the
checker's extractive text rule clearly, indices were implicit array positions,
and retries received feedback without the rejected JSON. The repair adds a
derived source view with explicit indices while preserving the source
snapshot, includes the preceding rejected candidate with complete feedback,
and makes verbatim text and missing-field rules explicit. It also asks the
agent to preserve alternative admission routes and published qualifications.
The checker, API schema, source fixture, and permissions remain unchanged.

Two new workflow regression tests first failed against the old runner (one
failure and one error). After the repair, all 28 available course tests passed
in the review workspace using stubbed model calls and mocked collection.
The revised test baseline retains the Introduction admission alternatives,
conditional admission, and approved trades. An in-memory diagnostic replay of
the archived third candidate passed the unchanged checker after adding only
its four omitted flags; this was not a new model run and was not published.
A real WSL rerun and the full repository suite still need verification.

## Successful real checkpoint -- 2026-10-28

The subsequent ordinary-WSL full suite passed 65 tests in 3.773 seconds with
exit code 0. The actual course workflow then completed with exit code 0 on
extraction attempt 1 and published `out/training/courses.json` and
`out/training/comparison.md`. Evidence is retained at
`out/training/run-20261028T165059Z-SOo49E`.

The published comparison contains the reviewed deadlines and exact starts
for Introduction and PLS, the published zero study fees with materials-cost
qualifications, the Introduction admission alternatives and conditions, and
the earlier-module prerequisites. Robot and Regulation retains a planned
autumn 2027 period, no current applications, and unknown exact start,
deadline, and fee. Source links, retrieval timestamps, and uncertainty flags
remain visible. The earlier failures above remain part of the evidence;
their pending-verification statements describe their historical checkpoints.

This proves one successful real-input walking-skeleton path. It is not an
estimate of general model accuracy, proof of semantic completeness for future
inputs, or completion of the final exam budget and stress-testing work.
