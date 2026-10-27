# W43 context notes

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
