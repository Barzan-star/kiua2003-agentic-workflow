# Retained course evaluation and deterministic repairs

The accepted Compulsory 2 skeleton compares three Fagskolen Innlandet modules.
Later work adds repeatable evaluation, enforced budgets and source-bound
validation. Model-generated results and deterministic verification stay separate.

| Measure | 8 November baseline | 10 November Task 015 trial |
|---|---:|---:|
| Eligible cases scored | 7/7 | 7/7 |
| Expected source rejections before provider calls | 2/2 | 2/2 |
| Final checker acceptance | 5/7 | 7/7 |
| First-attempt acceptance | 4/7 | 2/7 |
| Correct scalar slots | 144/147 | 144/147 |
| Required text coverage | 119/119 | 119/119 |
| Prerequisite atom coverage | 77/77 | 77/77 |
| Incorrect populated claims | 2/89 | 3/90 |
| Final exact source URLs | 19/21 | 21/21 assembled |
| Raw final model exact URLs | 19/21 | 19/21 |
| Generation / input-count requests | 12 / 12 | 12 / 12 |
| Confirmed total tokens | 86,322 | 85,528 |

Both trials use gpt-6-luna, low reasoning, Python 3.12.3, openai==3.46.0,
the same frozen corpus/reference and declared limits. Rejected final candidates
remain in the fixed denominator. These single trials on variants of three
courses do not estimate unseen-course accuracy, statistical significance or
isolated causal model improvement. The WSL kernel patch changed; implementation
changes are hash-recorded. URLs are outside the 147 scalar slots. Metadata
assembly improved fidelity; raw model URL copying did not improve.

Baseline: out/course-evaluations/run-20261108T155558.513345Z-54fe16fa/.
Task 015: out/course-evaluations/run-20261110T142507.391133Z-ca876b9b/.
The Task 015 ZIP SHA256 is
`83d9c531f5fc28b517749c3321a9da07508f4af26a41ae1b1ec4f726cf3e7392`.

## Case interpretation

The newer final candidates retain admission alternatives/qualifications,
module prerequisites, fee/materials distinctions and required unknowns. S05
abstains on Introduction dates from conflicting offerings. S06 does not follow
the targeted forged deadline 2030-12-31 or fee 999999; this is one observed
target, not a general security guarantee. Atom coverage and AI-assisted
inspection do not substitute for student qualitative confirmation.

The three new scalar errors repeat exact starts in planned_period: S05 PLS
and S06 Introduction/PLS. The dates exist in the sources and already occupy
start_date; their role as an approximate period is wrong. Newlines also split
three Markdown rows. The production checker accepted the values while the
independent scorer identified representation errors.

## Task 016 repair and evidence

The precision guard rejects supported full-date syntax in planned_period.value,
retaining seasons, month/year periods, quarters and the null contract. It checks
the selected value, not unrelated dates in its evidence quote. The prompt
forbids deriving periods by dropping exact dates' days. Table formatting keeps
whitespace/pipes in display cells without changing JSON or evidence.

Ordinary WSL reproduced ten failures among fifteen focused controls before
repair; all fifteen passed after it. The full suite passed 328 tests with no
failures, errors or skips. Corpus/replay, isolated legacy probe/check, previews
and whitespace checks passed. All 10,090 protected entries, index and tags
were preserved. Verification ZIP SHA256:
`fd3efdac87a5a8b65e096624418db851d80439fc696b34ebbcc24a805b8fa0bd`.

An offline recheck of the seven retained candidates now accepts five and rejects
S05/S06 for those three wrong-field values. No candidate or historical score
was changed, and no model was rerun. This proves a stronger gate, not improved
model generation. Task 017 adds the controlled stress study documented separately.

## Final reporting

The README distinguishes normal model execution, component replay and offline
stress reproduction. Raw historical runs remain under ignored out/ for the
required evaluation appendix. The selected replay fixtures make the stress
study reproducible without those directories.

The final paper must describe the actual controller, justify the departure
from Codex-process extraction, retain failures/limits and include student-edited
qualitative discussion. Demonstration/feedback, final paper/appendix review and
the exam tag remain separate. Source-change/layout tracking is still a planned
post-demonstration item from Compulsory 2, not a completed capability here.
