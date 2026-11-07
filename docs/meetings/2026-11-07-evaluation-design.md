# Task 013 evaluation design session

Date: 2026-11-07

## Decisions

- Implement Phase A only: fixed source cases, prepared reference facts, deterministic generation, corpus validation, and this record. Scoring, replay, model execution, budget enforcement, and production-runner changes remain future work.
- Keep all source-case labels, expected outcomes, reference facts, and synthetic provenance in the catalog, reference file, and separate case manifests. The generated source bundle contains only the source objects and the specific declared mutation.
- Use the exact frozen `fixtures/courses/course-sources.json` bytes as S00 and as the base for all transformations. Its verified SHA-256 is `1ff359c0251075a2274fb037c8c478d4d5ded1e12cf709be5feb0831222a4546`.
- Make transformations deterministic and fail with a named match-count error if any expected source text is missing or duplicated. Use zero-based source section indices in manifests.
- Check valid and rejected bundle expectations with the collector's pure `_valid_bundle` preflight. The corpus utility does not collect sources, invoke extraction, query the candidate checker, or score candidates.
- For S04, remove the Introduction fee value, fee table column and cell, and the duplicate no-study-fee sentence in both repeated fee sections. Keep the books and other study materials cost sentence in both sections.
- Store source-grounded facts and quotations independently from candidate null/evidence/missing-flag rules. Unknown facts have no fabricated quote; each has an absence or ambiguity rationale and the applicable source-scope hash.
- Record reference review status as `prepared`. Coding-agent assistance was used to prepare 32 base facts and six case-specific override facts (24 quoted base facts, eight base unknowns, and four unknown overrides). A separate source review was pending at this checkpoint. Candidate qualitative review remains `pending`.

## Initial preparation checkpoint (earlier results)

- Generated and checked S00–S08. S00 retains the original input bytes exactly. The collector preflight accepts S00–S06 and rejects S07–S08 as declared.
- The generated export is `out/exam/task-013/generated-cases-final/`; each source input is separate from its manifest, and each manifest records the base hash, case ID, transformation version, input hash, and changed section indices.
- `python3 harness/course_evaluation_cases.py --check`: exit 0; nine cases and the prepared reference passed structural, hash, and quotation-membership checks.
- `python3 -m unittest discover -s tests -p 'test_course_evaluation_cases.py'`: exit 0; 9 tests passed.
- At this earlier checkpoint, repository checks passed:
  `python3 harness/probe.py --offline && python3 eval/check_probe.py`; the full
  suite ran 93 tests with 2 skipped; `git diff --check` and
  `git diff --exit-code HEAD` exited 0. These results precede the post-repair
  ordinary-WSL verification below.
- The frozen source fixture and `out/training/course-sources.json`, `courses.json`, and `comparison.md` remained byte-for-byte unchanged. Their hashes are recorded in `out/exam/task-013/phase-a-checks.log`.
- Complete commands, outputs, and exit codes are in `out/exam/task-013/phase-a-checks.log`. The review ZIP is `out/exam/task-013/task-013-corpus-review.zip`.

## Remaining work and status at the initial preparation checkpoint

- Source values, quotations, unknown rationales, and case coverage have now been checked in the separate review below. Reference status is `reviewed`, with a dated, hash-bound record. This is not a claim of human review or candidate semantic evaluation.
- Qualitative review of candidate semantics remains `pending`.
- At this checkpoint Phase B and later bounded model-evaluation work were not
  implemented; their acceptance commands were **NOT RUN**.
- No real model execution, network collection, scoring, replay, or production-runner change occurred in this phase.


## Source review and regression repair

- Checked all 38 stored base/override fact entries against the frozen and
  generated source inputs. The reference now has 32 applicable logical facts
  in each accepted case, including S05's planned-period unknown.
- Retained the literal supporting quotations and used core expected phrases
  for text values, including `høsten 2027` and the delivery-format wording.
  Optional sentence prefixes and list numbers are not required text atoms.
- Removed source-visible test labels from S05 and revealing wording from S06.
  Their synthetic provenance remains in the catalog and manifests. The two
  source rejection controls still fail the collector's pure preflight.
- Added checks for complete per-case coverage, value types and valid field
  paths, nonnegative section indices, per-case quotation membership, declared
  transform targets, pending candidate qualitative review, and safe export.
- New regression cases exposed 22 failing subcases in a 20-test run before
  repair. The repaired 21-test corpus suite passes; the available 68-test
  course-component suite also passed at this earlier repair checkpoint.
  Existing source and production-code hashes were unchanged. These component
  checks did not include the complete repository suite.
- Versioned the corrected catalog/reference as version 2 and transformations
  as `task-013-phase-a-v2`. The source-review record binds the reviewed facts
  to the original source and every generated case hash. Corpus checking never
  completes candidate qualitative review.
- At this source-review checkpoint Phase B, budget enforcement, and real-model
  evaluation remained unimplemented.

## Phase A post-repair ordinary-WSL verification checkpoint — 2026-11-07

- The corpus/reference check passed for all nine source cases.
- `python3 harness/probe.py --offline && python3 eval/check_probe.py` passed.
- All 105 repository tests passed with no skips.
- The frozen source fixture and all three normal training outputs passed their
  checksum checks. Both `git diff --check` and `git diff --cached --check`
  passed.
- Full evidence is in
  `out/exam/task-013/wsl-review-gTgl8K/verification.log`.
- The reference source review is complete. Candidate qualitative review
  remains `pending`; Phase B remains unimplemented.

## Initial Phase B implementation checkpoint — 2026-11-07

- Added a standard-library scorer separate from `eval/check_courses.py`. It
  verifies the reviewed reference and its source, generated-case, and content
  hashes before scoring. Each accepted candidate has 21 value slots and 17
  known text atoms; the 11 prerequisite atoms have a separate coverage result.
- Added offline replay for all nine source cases and nine candidate mutations.
  Positive controls are `synthetic_reference`; mutations are
  `mutated_candidate` with source case, mutation ID, parent hash, and candidate
  hash. The replay stores generated inputs/manifests, checker feedback,
  applicable rendered outputs, per-field scores, run/input/implementation
  hashes, integrity results, and a readable summary. It does not import
  recorded-model candidates.
- Corpus/reference validation passed for nine source cases. The focused Phase B
  suite passed all 15 tests with no skips. The default replay passed in
  `out/course-evaluations/run-20261107T125143.482270Z-12102324`.
- All nine source preflight expectations matched: seven accepted cases passed
  the unchanged checker and renderer; S07/S08 were rejected before checker or
  rendering. Five expected-rejection mutations were rejected and four
  checker-pass sensitivity mutations passed; all four passing mutations were
  rendered.
- Positive controls covered 147/147 value slots, 119/119 known-text atoms,
  and 77/77 prerequisite atoms. Mutation controls scored 180 correct, 2
  missing, and 7 incorrect value slots of 189, with 143/153 known-text atoms
  and 90/99 prerequisite atoms covered. These synthetic component outcomes do
  not measure model accuracy or instruction resistance; checker outcomes are
  reported separately from factual defects.
- The frozen source, reviewed reference, and all three normal training outputs
  retained their hashes. Both Git diff checks passed. Commands and exit codes
  are in `out/exam/task-013/phase-b/`; full replay evidence is in the run
  directory above. The complete repository suite is deferred to ordinary WSL
  after review.
- `--actual` is disabled before subprocess dispatch. No model or network call
  was made. Candidate qualitative review remains `pending`; actual evaluation,
  budget enforcement, and recorded-model import remain later work.


## Phase B review and regression repair

- Found that overall replay success depended on checker/render outcomes but
  did not assert the scorer's expected effects. A controlled score-report
  mutation made every deliberate fault appear perfect, yet the initial gate
  passed. The repaired gate rejects it and reports all nine missed effects.
- Require the complete case set, all seven positive scoring expectations,
  all nine mutation scoring expectations, consistent detail/count results,
  and input/output integrity for a replay pass. Expected checker results and
  expected scoring results are reported separately.
- Fixed fresh-checkout test setup and the collision test. Added output-path
  guards, bounded component dispatch, typed schema/provenance checks, and
  failure finalisation with stage traces, partial evidence, and unscored slots.
- The expanded pre-repair run had 9 failures and 4 errors in 25 tests.
  Final review checks passed 27 Phase B tests and 95 available course-component
  tests. Repaired replay `out/course-evaluations/run-20261107T131903.943969Z-e94cbd5d` passed 7/7 positive
  and 9/9 mutation scoring controls, as well as the original source/checker
  expectations. At this checkpoint full repository verification remained
  pending in ordinary WSL; its completion is recorded below.
- Phase A corpus/reference and production code/test hashes are unchanged.
  The initial replay evidence is retained. No real-model evaluation or source
  collection was performed; candidate qualitative review remains pending.


## Completed ordinary-WSL Phase B verification — 2026-11-07

- Corpus/reference validation passed for all nine source cases. Offline replay
  passed: all nine source preflight expectations matched, with seven accepted
  cases and two expected source rejections. All 5/5 expected checker-rejection
  mutations and 4/4 checker-pass sensitivity mutations matched; all four
  checker-pass mutations rendered without failure.
- Scoring controls matched 7/7 positive and 9/9 mutation expectations.
  Positive `synthetic_reference` controls scored 147/147 value slots, 119/119
  required-text atoms, and 77/77 prerequisite atoms. `mutated_candidate`
  controls scored 180 correct, 2 missing, and 7 incorrect value slots of 189,
  with 143/153 required-text atoms and 90/99 prerequisite atoms covered.
  Replay integrity passed. These synthetic controls do not measure model
  accuracy or instruction resistance.
- The offline probe and checker passed. All 132 repository tests passed with
  no skips. All six source, reference, and published-output checksum checks
  passed, along with whitespace and protected-path diff checks.
- Verification log:
  `out/exam/task-013/wsl-phase-b-rW0DJI/verification.log`. Detailed replay
  results:
  `out/course-evaluations/run-20261107T133047.144244Z-3671390d/results.json`.
- Candidate qualitative review, budget enforcement, and actual model
  evaluation remain future work. No model evaluation or source collection was
  performed.
