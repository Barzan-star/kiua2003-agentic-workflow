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

## Task 002 — MET Norway HTTP cache

- Normal runs use `out/met_hamar_cache.json` for the forecast and HTTP metadata; offline runs continue to read the saved fixture only. Expired entries refresh conditionally with the exact saved `Last-Modified` value. A `200` replaces the cache; a `304` reuses the forecast and updates supplied metadata.
- Missing or invalid cache data triggers a refresh. Missing or invalid `Expires` means immediate expiry; a missing `Last-Modified` omits the conditional request header. Failed refreshes report an error instead of serving expired data.
- Review found that `_valid_forecast` accepted an empty `timeseries` and malformed entries. This could bypass refresh or let invalid `200` data replace a good cache. Validation now requires the fields consumed by the probe, parseable timestamps, and at least one usable finite numeric temperature entry.
- The initial regression run had two failures and one error. After the validation fix, all nine cache tests passed.
- Verification used offline fixture input and mocked HTTP responses. No live API request was tested. `eval/` and `fixtures/met_hamar.json` remained unchanged.
