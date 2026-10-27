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
