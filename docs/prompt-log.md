# Prompt log

## 2026-10-03 — Task 001 MET Norway probe
Codex initially proposed adding contact details to the MET Norway User-Agent.
I rejected that assumption because the project must avoid personal data.
The plan was revised to use the non-personal User-Agent `kiua2003-agentic-workflow/0.1`.

During implementation, Codex could not reach MET Norway because DNS failed inside its sandbox.
It did not fabricate a fixture. I ran the acceptance command myself from Ubuntu, obtained the real MET data, and verified both online and offline runs with `eval/check_probe.py`.
