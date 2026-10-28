# Task 004: Checked headless summary

## Goal
Add a headless summary validation step that checks generated weather text
against the probe data. The checker and its deterministic tests use no model
or network access and require no user interface; separate headless generation
uses the configured model service.

## Scope
- Add `eval/check_summary.py` to validate `out/summary.md` against
  `out/probe.json` by default, with path overrides for deterministic tests.
- Require 20–80 whitespace-separated words, a case-insensitive mention of
  Hamar, the input minimum and maximum temperatures with Celsius units, and no
  Celsius temperature absent from the probe input.
- Keep validation importable without reading files at import time.
- Add standard-library tests in `tests/test_summary_check.py`.
- Prepare `harness/prompts/summarise.md` with bounded, temperature-only
  instructions for a headless summary stage.
- Add a separate `course_summary` permission profile in `.codex/config.toml`
  for headless generation; it restricts commands executed by the agent.
- Keep the checker and its deterministic tests free of model calls, network
  access, and third-party dependencies.

## Acceptance
- Tests cover a valid summary, missing Hamar, too few and too many words,
  missing an extreme, an invented temperature, and a missing summary file.
- Equivalent numeric formatting such as `5` and `5.0` is accepted.
- The checker prints `PASS` only when every validation succeeds and exits
  nonzero with a clear error for missing files or invalid content.
- `python3 -m unittest discover -s tests` passes.
- The initial checker test, before generation, reported the missing default
  summary because `out/summary.md` did not yet exist.

## W43 simulation results
- The first headless attempt could not execute read commands because the
  sandbox could not access the Codex runtime; its final paragraph failed the
  checker. A narrow read permission for the versioned NVM runtime fixed this,
  verified with `codex sandbox`.
- The next two headless attempts both passed the checker with different
  wording. Both saved outputs, `out/summary-run2.md` and `out/summary.md`,
  pass validation.
- The saved input contains 83 entries from 3–13 October 2026, with minimum
  -0.3 °C and maximum 16.6 °C. No live MET request was tested.
- The checker validates 20–80 whitespace-separated words, a case-insensitive
  Hamar mention, the input minimum and maximum with °C, and absence of °C
  temperatures not present in the input. It does not validate historical
  framing or other claims.
