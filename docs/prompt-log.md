# Prompt log

## 2026-10-28 — Task 008 offline CI checkpoint
Prompt summary: prepare the offline GitHub Actions checks and record local
verification plus the fresh-context task-planning check.

Local verification passed: SDK imports for `Client` and `MCPServer`, Bash
syntax, both runner dry-runs, offline probe and checker, all 35 tests,
whitespace check, and protected-path diff check. GitHub Actions has not run
yet. The fresh-context `$task-plan 005` test recognised the completed
implementation, marked acceptance commands **NOT RUN**, and left the worktree
clean.

## 2026-10-28 — Task 009 MET request protocol corrections
Prompt summary: correct the request coordinates and compression handling,
record regression and verification results, and preserve the limits of the
mocked HTTP coverage.

The Task 009 regression tests exposed the previous longitude precision and
missing compression handling. After the fix, all 11 focused cache tests and
all 37 full-suite tests passed. The offline probe and checker, whitespace
check, and protected-path diff check passed. HTTP responses were mocked; live
MET requests and schedules remain untested. PR #2's initial GitHub Actions
run (40663441912) passed all 35 tests before Task 009; GitHub Actions has not
tested Task 009.

## 2026-10-28 — Final W43 debrief
Prompt summary: record merged Task 008/009 results, the disposable breaking
CI demonstration and its restoration, and backup references for verified
workflow controls and limits.

PR #2 merged as `932aec3`; Task 009 commit `906f973` passed CI run
`40666992808`, and the latest local full suite passed all 37 tests. Demo PR #3
commit `900539c` failed with `AssertionError: empty title` in CI run
`40668294754`; revert `f6e54f1` restored local PASS and CI run
`40668817917`. PR #3 closed without merging, both demo branches were deleted,
and the restored demo tree matched `main`.

The final notes retain the documented repairs and limits: the fixture is
historical; fixture input does not prevent model-service network access; the
summary checker has limited factual and freshness coverage; attempt logs
separate candidate, prompt, checker, event, stdout, and stderr data; Codex's
ephemeral mode does not remove instructions or configured permissions; and
attempt/time limits do not cap dollar spend. MCP module launch fixed imports,
with stdio kept separate from stderr; workflow-scope recovery is specific to
the matching OAuth push error. Reviewer agents, agent SDKs, hooks, and
scheduling remained concepts only. Live MET requests remain untested, and
repository-specific tag publication is pending.

## 2026-10-28 — Task 006 W43 MCP checkpoint
Prompt summary: document the completed offline MCP demonstration, observed
filesystem and forecast tool behavior, implementation fixes, regression
results, and the boundaries of what the workflow implements.

The filesystem MCP server allowed `fixtures/` and rejected reading `AGENTS.md`
outside it. The custom MET server connected in Codex CLI 0.165.0 with one
forecast tool and returned 24 usable historical forecast entries from
`2026-10-03T09:00:00Z` through `2026-10-04T08:00:00Z`; their minimum was 5.3 °C
at `2026-10-04T06:00:00Z`. They are not observations or current weather.
Module-mode launching fixed the package-import failure, and filtering before
limiting fixed selection when an earlier entry lacked temperature.

The stdio regression timed out inside Codex's command environment but passed
directly in WSL; the precise environmental cause remains unconfirmed. The full
`.venv` suite passed in WSL with 35 tests, no skips, and exit code 0. Run it
from a normal WSL shell with `.venv/bin/python -m unittest discover -s tests`.
No live MET request was made. The MCP demo selects up to 24 usable entries,
while the workflow summary uses all probe items. Reviewer subagents and agent
SDKs were covered conceptually; the implemented workflow uses Bash
orchestration and MCP tools.

## 2026-10-28 — Task 005 checked workflow checkpoint
Prompt summary: document and commit the completed orchestration checkpoint,
including the successful offline run, checker result, evidence location, and
stub-based retry and failure coverage.

The deterministic suite passed all 28 tests. The actual
`./harness/run.sh --offline` execution exited 0 on summary attempt 1; the
published summary independently passed its checker with exit code 0 and
included -0.3 °C and 16.6 °C. Evidence is in
`out/workflow-20261028T065410Z-mTeyor`. No live MET request was made. Retry
and failure paths were tested with stubs and were not exercised in this
successful model run.

## 2026-10-03 — Task 001 MET Norway probe
Codex initially proposed adding contact details to the MET Norway User-Agent.
I rejected that assumption because the project must avoid personal data.
The plan was revised to use the non-personal User-Agent `kiua2003-agentic-workflow/0.1`.

During implementation, Codex could not reach MET Norway because DNS failed inside its sandbox.
It did not fabricate a fixture. I ran the acceptance command myself from Ubuntu, obtained the real MET data, and verified both online and offline runs with `eval/check_probe.py`.

## 2026-10-27 — W43 context exercise
Prompt summary: record where shared rules, task goals, MET-specific guidance, and fixture data belong; capture context-use observations and the result of a fresh-chat instruction check.
Prompt summary: load the met-api skill in a read-only test and report its temperature path, caching guidance, and whether it proves caching exists in the probe implementation.
The exercises confirmed the listed check commands, editing and personal-data rules, skill location, temperature path, and caching instructions. No HTTP caching code was added.

## 2026-10-27 — Task 002 MET Norway HTTP caching
Prompt summary: implement MET HTTP caching while preserving fixture-only offline runs, test cache refresh and failure behavior deterministically, and document the agreed cache policies and verification results.

The implementation stores the forecast with `Expires` and `Last-Modified` metadata in `out/met_hamar_cache.json`, reuses valid unexpired entries, refreshes expired entries conditionally, and reuses the saved forecast after `304`. Review found that empty or malformed forecast data could be reused or saved; the initial regression run had two failures and one error, followed by nine passing tests after validation was strengthened. Verification used offline fixture input and mocked HTTP responses; no live API request was tested.

## 2026-10-27 — W43 simulation, Tasks 003 and 004
Prompt summary: document reproducible offline workflow-preview and headless
summary commands, record simulation results, and verify the saved summaries.

The first headless attempt could not execute read commands because its
sandbox could not access the Codex runtime, and the final paragraph failed
the summary checker. A narrow read permission for the versioned NVM runtime
fixed access, verified with `codex sandbox`. The following two headless
attempts passed with different wording. The saved input contains 83 entries
from 3–13 October 2026, with minimum -0.3 °C and maximum 16.6 °C. The
checker enforces 20–80 words, Hamar, both extremes with Celsius units, and
no Celsius temperature absent from the input; it does not validate framing
or other factual claims. No live MET request was tested.
