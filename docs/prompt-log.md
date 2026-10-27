# Prompt log

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
