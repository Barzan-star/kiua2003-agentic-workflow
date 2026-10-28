# W43 context notes

## Task 008 — offline CI checkpoint (2026-10-28)

- Local verification passed: SDK imports (`Client` and `MCPServer`), Bash
  syntax, both runner dry-runs, offline probe and checker, all 35 tests,
  whitespace check, and protected-path diff check.
- PR #2's initial GitHub Actions run, 40663441912, passed all 35 tests before
  the Task 009 changes. GitHub Actions has not tested Task 009.
- The fresh-context `$task-plan 005` test passed: it recognised the completed
  implementation, marked acceptance commands **NOT RUN**, and left the
  worktree clean.

## Task 009 — MET request protocol checkpoint (2026-10-28)

- Regression tests exposed the previous longitude precision and missing
  compression handling. After the fix, all 11 focused cache tests and all 37
  full-suite tests passed.
- The offline probe and checker, whitespace check, and protected-path diff
  check passed.
- Task 009 commit `906f973` passed GitHub CI run `40666992808`. HTTP responses
  were mocked. Live MET requests and schedules remain untested.

## Final W43 debrief and backup reference (2026-10-28)

- PR #2 merged as `932aec3`. The latest full local suite passed all 37 tests.
- Demo PR #3's breaking commit `900539c` produced `AssertionError: empty
  title` in CI run `40668294754`. Revert `f6e54f1` restored local PASS and
  successful CI run `40668817917`. PR #3 was closed without merging; its
  local and remote demo branches were deleted. The restored demo tree matched
  `main`.
- Existing faults and repairs: Task 009 corrected longitude precision and
  compression handling; Task 006 fixed module-mode MCP launching and filtered
  usable forecast entries before limiting; Tasks 003–005 resolved restricted
  Codex runtime reads and completed the checked workflow. Earlier cache
  validation and summary-attempt evidence remains in the task records above.
- Offline fixture input does not make summary generation offline: the model
  service is still contacted. Fixture timestamps are historical. The summary
  checker validates length, Hamar, supplied extremes, and unsupported Celsius
  values, but does not establish freshness or verify other factual claims.
  Workflow attempts retain separate candidates, prompts, checker feedback,
  event output, stdout/stderr logs, and probe logs.
- Codex output, ephemeral execution, and the `course_summary` permission
  profile were verified. Ephemeral runs still follow the supplied
  instructions and configured permissions. Attempt and time limits are not a
  dollar cap.
- MCP troubleshooting established module-mode launch as the package-import
  fix and kept protocol stdout separate from stderr logs. The stdio test
  timed out in Codex's command environment and passed directly in WSL; the
  cause remains unconfirmed.
- Workflow-scope recovery applies only to the matching OAuth push error.
  Repository-specific tags were discussed; tag publication is still pending.
- Reviewer agents, agent SDKs, hooks, and scheduling were discussed as
  concepts, not implemented. Live MET requests remain untested.

## Task 006 — MCP checkpoint (2026-10-28)

- The filesystem MCP server allowed `fixtures/` and rejected reading
  `AGENTS.md` outside that directory.
- The custom MET server connected with one forecast tool in Codex CLI 0.165.0.
  It reported 24 usable entries from `2026-10-03T09:00:00Z` to
  `2026-10-04T08:00:00Z`. Their minimum is 5.3 °C at
  `2026-10-04T06:00:00Z`. They are historical forecasts, not observations or
  current weather.
- Module-mode launching fixed the package-import failure. Filtering usable
  entries before limiting fixed selection when an earlier entry lacked
  temperature.
- The stdio regression timed out inside Codex's command environment and
  passed directly in WSL. The precise environmental cause remains
  unconfirmed.
- The complete `.venv` suite passed directly in WSL: 35 tests, no skips, exit
  code 0. The full-suite command for a normal WSL shell is
  `.venv/bin/python -m unittest discover -s tests`.
- No live MET request was made.

The MCP demo selects up to 24 usable entries, while the existing workflow
summary uses all probe items. Reviewer subagents and agent SDKs were covered
conceptually; the implemented workflow uses Bash orchestration and MCP tools.

## Task 005 — checked workflow checkpoint (2026-10-28)

- The deterministic suite passed all 28 tests.
- `./harness/run.sh --offline` ran successfully with workflow exit code 0 on
  summary attempt 1.
- The published `out/summary.md` independently passed its checker with exit
  code 0 and included minimum -0.3 °C and maximum 16.6 °C.
- Evidence directory: `out/workflow-20261028T065410Z-mTeyor`.
- No live MET request was made. Stubs covered retry and failure behavior;
  those paths were not exercised during this successful model run.

## Task 003 and Task 004 — offline summary simulation

- `./harness/run.sh --offline --dry-run` previews the workflow; the runner
  does not execute its probe or summary stages yet.
- The saved probe input contains 83 entries spanning 3–13 October 2026. Its
  minimum is -0.3 °C and its maximum is 16.6 °C.
- The first headless summary attempt could not execute read commands because
  the sandbox could not access the Codex runtime. Its final paragraph failed
  `eval/check_summary.py`. Adding a narrow read permission for the runtime
  fixed the problem; `codex sandbox` verified access. The next two headless
  attempts both passed the checker and used different wording.
- Both saved successful summaries, `out/summary-run2.md` and
  `out/summary.md`, pass `eval/check_summary.py`.
- The checker tests word count (20–80), a case-insensitive Hamar mention,
  presence of the probe minimum and maximum with °C, and rejects any °C
  temperature absent from the probe. It does not check historical/current
  framing or other factual claims.
- Offline refers to the saved weather input. The headless summary still uses
  the configured model service. No live MET request was tested.

## Context — 2026-10-27

Context belongs in the file that matches its scope and when it is needed:

- `AGENTS.md` holds shared project rules and check commands because they apply across tasks.
- `tasks/*.md` holds individual task goals and acceptance criteria because those details are specific to each task.
- `.agents/skills/met-api/SKILL.md` holds MET-specific instructions loaded when needed, keeping domain guidance available for relevant work.
- `fixtures/met_hamar.json` holds forecast data read through tools when needed; it is data, not project instructions, and should be treated according to the skill's offline and timestamp guidance.

Observed results from the context exercises:

- An earlier context exercise showed 1% used before reading the complete fixture and 5% afterward.
- An earlier fresh chat showed 1% used and answered `UNKNOWN` for the unread fixture timestamp.
- The latest fresh-chat test correctly returned both check commands, the `eval/` editing rule, the personal-data rule, and the skill location.
- The explicit met-api test returned the correct temperature JSON path and caching instructions.
- The context indicator showed 1% used after the latest skill self-test.
- No HTTP caching code was added during these exercises.

## Task 002 — MET Norway HTTP cache

- Normal runs use `out/met_hamar_cache.json` for the forecast and HTTP metadata; offline runs continue to read the saved fixture only. Expired entries refresh conditionally with the exact saved `Last-Modified` value. A `200` replaces the cache; a `304` reuses the forecast and updates supplied metadata.
- Missing or invalid cache data triggers a refresh. Missing or invalid `Expires` means immediate expiry; a missing `Last-Modified` omits the conditional request header. Failed refreshes report an error instead of serving expired data.
- Review found that `_valid_forecast` accepted an empty `timeseries` and malformed entries. This could bypass refresh or let invalid `200` data replace a good cache. Validation now requires the fields consumed by the probe, parseable timestamps, and at least one usable finite numeric temperature entry.
- The initial regression run had two failures and one error. After the validation fix, all nine cache tests passed.
- Verification used offline fixture input and mocked HTTP responses. No live API request was tested. `eval/` and `fixtures/met_hamar.json` remained unchanged.
