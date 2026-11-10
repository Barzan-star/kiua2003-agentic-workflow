# Task 016: Planned-period precision and comparison table integrity

## Purpose and accepted project scope

Extend the accepted Compulsory 2 three-course comparison. Its risk analysis
identifies source-supported facts placed in the wrong field. This task repairs
one measured instance and a presentation defect; it does not change the local
problem, course set, reference facts, scorer, budget or collection policy.

## Retained observation

The declared Task 015 trial is
`out/course-evaluations/run-20261110T142507.391133Z-ca876b9b/`.
All seven eligible cases passed the production checker, while the independent
scorer retained 144 correct of 147 scalar slots. S05's PLS record and S06's
Introduction and PLS records repeat published exact start dates in
`planned_period.value`. The exact dates are genuine source facts but are not
separately published approximate periods. They already occupy `start_date`.
Their newlines also split three rows in the two rendered case tables.

In S05, the first checker rejection identifies a supplied planned period also
marked missing. The retry removes that flag, keeps the exact-date period and
passes. Thus a consistency repair exposes the missing precision constraint.
The earlier trial and every raw response remain historical evidence.

## Repair

- Reject full-date syntax in `planned_period.value`: supported Norwegian
  written dates, numeric dates and ISO dates, even when the calendar date is
  invalid. Inspect the value rather than unrelated dates in its evidence
  quotation. Preserve null/missing rules, exact-start validation, and explicit
  seasons, month/year periods and quarters.
- Clarify the extraction prompt: never repeat an exact start as a planned
  period or manufacture one by dropping the day. An absent independently
  published approximate period remains null with empty evidence and its flag.
- Normalize table-cell display whitespace and escape literal backslashes and
  pipes. This changes Markdown presentation only, preserving JSON and evidence.
- Add fifteen offline regressions, including the three observed errors,
  positive approximate-period controls, valid multi-line/pipe input, materials
  text and non-mutation of records.

The precision guard is deliberately limited to the checker's supported date
grammars. It is not a general semantic proof that any other text denotes an
independently published approximate period. Human source-context review remains
necessary. Table formatting is likewise not a general Markdown sanitizer.

## Test-first evidence and acceptance

The isolated review ran fifteen focused tests before the repair: ten assertion
failures, five passes and no errors or skips. After repair all fifteen passed.
All 314 SDK-independent repository checks passed without errors or skips.
The twelve pinned OpenAI SDK tests and two MCP integration tests cannot be
verified in that review runtime. The ordinary-WSL acceptance gate must run
the full 328-test suite with the project's existing pinned dependencies and
zero skips; no package installation is part of this task.

The one-file integration helper checks the reviewed branch, HEAD, working
scope, input hashes and retained trial before applying these changes. It backs
up the seven target files, records before/after focused results, runs the full
suite, corpus/replay, probe/checker and runner previews, then checks preservation
and whitespace. Failure restores only helper-owned changes whose bytes still
match. It creates an evidence ZIP for review and leaves successful work
uncommitted.

An offline recheck of the retained seven candidates must accept five and reject
S05/S06 for their three planned-period fields after repair. This shows the
stronger gate, not a new model trial or an improvement to the historical score.
No provider call, staging, commit, push or tag change is required.

## Ordinary-WSL acceptance (2026-11-10)

The focused before run reproduced ten assertion failures in fifteen tests;
all fifteen passed after repair. The full suite passed 328 tests
with zero failures, errors or skips. Corpus, offline replay, unchanged
probe/checker in an isolated copy, runner syntax/previews and whitespace
checks passed. The retained-output recheck rejected S05 and S06 for three
planned-period fields; it did not alter or rerun the model trial.

Evidence: `out/exam/task-016/repair-20261110T160827Z-aec0d8d7/`. No model request, installation,
staging, commit, push or tag change was performed.
