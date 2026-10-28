# Task 003: Dry-run workflow

## Goal
Add an executable Bash entry point that previews the agentic workflow without
running any stages, checks, model calls, or network requests.

## Scope
- `harness/run.sh`: parse `--offline` and `--dry-run`, print stage inputs,
  outputs, and checks, and reject unknown arguments.
- `README.md`: document the dry-run commands and explain that actual execution
  is not wired yet.
- Keep the probe, tests, fixture, and `eval/` unchanged. Do not remove or
  modify files under `out/` while previewing the workflow.
- Use Bash and existing project tools only; add no dependencies.

## Planned workflow
1. Probe stage: in offline mode, read `fixtures/met_hamar.json`; in normal mode,
   use `out/met_hamar_cache.json` when valid or the MET API as needed. Produce
   `out/probe.json` and check it with `eval/check_probe.py`.
2. Summary stage: consume `out/probe.json`, produce `out/summary.md`, and check
   it with `eval/check_summary.py`. This stage is **PLANNED** and not implemented.

## Acceptance
- `bash -n harness/run.sh` succeeds.
- `./harness/run.sh --offline --dry-run` and `./harness/run.sh --dry-run`
  succeed and print each stage's input, output, and check.
- Offline output identifies `fixtures/met_hamar.json -> out/probe.json` and
  `eval/check_probe.py`.
- Normal output identifies `out/met_hamar_cache.json` or the MET API as the
  probe input.
- The summary stage is clearly marked **PLANNED** and not implemented yet.
- Dry runs do not run the probe, checks, model, or network requests and do not
  create or modify output files.
- Calling the script without `--dry-run` exits nonzero with a clear message.
- Unknown arguments are rejected with a clear message.
