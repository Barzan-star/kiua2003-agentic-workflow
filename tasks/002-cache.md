# Task 002: Add HTTP caching to the MET Norway probe

## Goal
Make live requests respect MET's caching rules while preserving repeatable offline runs.

## Requirements
- `--offline` must read `fixtures/met_hamar.json` without network access or modifying the fixture.
- Normal execution must use a local HTTP cache under the ignored `out/` directory, separate from `out/probe.json` and the saved fixture.
- Reuse a valid cached response until its `Expires` time.
- When refreshing, send `If-Modified-Since` with the exact saved `Last-Modified` value.
- On `200`, update the cache with the response; on `304`, reuse its saved response.
- Report request failures clearly. Do not silently present expired cached data as fresh.
- Use HTTPS and an identifying application `User-Agent` with a project reference.
- Preserve the existing `out/probe.json` interface.
- Use Python's standard library only.

## Cache and validation policies
- Store the forecast and its `Expires` and `Last-Modified` values together in `out/met_hamar_cache.json`.
- If `Expires` is missing or invalid, treat the entry as expired. If `Last-Modified` is absent, omit `If-Modified-Since`.
- On `304`, keep the saved forecast and update either metadata value supplied by the response; retain saved values for omitted headers.
- Treat missing or invalid cache data as a cache miss. If refresh fails, report an error and do not serve expired cached data.
- Validate the forecast structure before reuse or saving: require parseable timestamps, the nested fields consumed by the probe, and at least one usable finite numeric temperature entry. Invalid `200` data must fail before replacing the cache.

## Actual implementation file scope
- `harness/probe.py`
- `tests/test_probe_cache.py`
- `README.md`
- `.gitignore` (ignore generated `__pycache__/` directories)
- `AGENTS.md` (include the test discovery command)
- `tasks/002-cache.md`, `docs/w43-notes.md`, and `docs/prompt-log.md` (record task decisions and results)

## Tests
Add deterministic tests using temporary directories and mocked HTTP responses. Cover offline behaviour, an unexpired cache, a `200` refresh, a `304` response, and a request failure. Tests must make no real network requests.

## Acceptance
All must pass:
- `python3 harness/probe.py --offline`
- `python3 eval/check_probe.py`
- `python3 -m unittest discover -s tests`
- `git diff --check`

## Constraints and out of scope
- Keep `eval/` and `fixtures/met_hamar.json` unchanged.
- Summary generation and automation are outside this task.
