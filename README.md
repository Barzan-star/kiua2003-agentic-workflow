# Agentic Workflow Course Project

The MET Norway probe reads `fixtures/met_hamar.json` when run with `--offline`.
This mode does not make a network request or change the fixture. Normal runs
reuse the HTTP cache at `out/met_hamar_cache.json` until its `Expires` time,
then refresh it from the MET Norway Locationforecast API. The generated probe
output remains at `out/probe.json`.

MET Norway forecast data is provided under the [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)
license. The live API terms are documented at
https://api.met.no/doc/TermsOfService.

## Workflow preview

Use the Bash runner to preview the workflow without executing any stages:

```sh
./harness/run.sh --dry-run
./harness/run.sh --offline --dry-run
```

The offline preview uses `fixtures/met_hamar.json` as the probe input. The
normal preview shows the HTTP cache or MET API as the source. Both previews
show the probe output and check, followed by a summary stage marked **PLANNED**
and not implemented yet. Actual execution is not wired; invoking the runner
without `--dry-run` exits with an error.

## Offline run

Prerequisites are Python 3, Bash, and the Codex CLI configured to use the
`gpt-6-luna` model service. Run every command below from the repository root.
The probe and its checker can be run without network access:

```sh
python3 harness/probe.py --offline && python3 eval/check_probe.py
./harness/run.sh --offline --dry-run
```

`run.sh` currently previews the workflow only. It does not execute either
stage. To generate a summary separately with the checked-in prompt and the
`course_summary` permission profile, use:

```sh
timeout --kill-after=5s 90s codex exec \
  --strict-config --ephemeral --json \
  -m gpt-6-luna \
  -c 'model_reasoning_effort="low"' \
  -c 'default_permissions="course_summary"' \
  -c 'approval_policy="never"' \
  -c 'web_search="disabled"' \
  -c 'agents.enabled=false' \
  -o out/summary.md - \
  < harness/prompts/summarise.md \
  > out/summary.events.jsonl \
  2> out/summary.stderr.log &&
python3 eval/check_summary.py
```

The CLI saves the generated paragraph to `out/summary.md` using `-o`, while
`course_summary` restricts the commands executed by the agent. The `&&`
connection ensures the checker runs only after successful generation.

Here, “offline” describes the saved weather input: `--offline` reads
`fixtures/met_hamar.json` without a live MET request. Generating a summary
still calls the configured model service. The summary permission profile
includes a read permission for the versioned NVM installation; that path
must match the Codex runtime installation used by the reader.

The first headless attempt could not execute read commands because the
sandbox could not access the Codex runtime, and its final paragraph failed
the checker. A narrow read permission for that runtime fixed the issue, as
verified with `codex sandbox`. The next two headless attempts both passed the
checker with different wording. The saved input has 83 entries from 3–13
October 2026, with temperatures ranging from -0.3 °C to 16.6 °C. No live MET
request was tested.

The summary checker verifies a 20–80 word count, a case-insensitive Hamar
mention, inclusion of the input minimum and maximum with °C, and that every
temperature stated with °C occurs in the probe input. It does not check the
summary’s historical/current framing, whether other claims are supported, or
that a generated summary was produced offline.
