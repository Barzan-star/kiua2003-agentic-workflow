# Agentic Workflow Course Project

## Task planning skill

Use the repository-local skill explicitly with a three-digit task number, for
example `$task-plan 005`, to get a read-only plan for the matching task file.
The skill reports the goal, current implementation state, proposed steps,
affected files, and exact acceptance commands marked `NOT RUN`. It does not
make changes or run those commands.

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
show the probe and checker stages, plus summary generation and validation with
up to three attempts. Preview mode does not execute commands or create files.
The runner resolves the repository root from its own path, so these commands
also work outside the repository directory.

## Offline run

Prerequisites are Python 3, Bash, GNU `timeout`, and the Codex CLI configured
to use the `gpt-6-luna` model service. An offline run uses the saved fixture
for the probe, but summary generation still calls the configured model
service. To execute the checked workflow:

```sh
python3 harness/probe.py --offline && python3 eval/check_probe.py
./harness/run.sh --offline --dry-run
./harness/run.sh --offline
```

The runner executes the probe, then its checker, before making any model call.
If either fails, it stops. Summary generation uses the checked-in prompt and
the verified headless Codex settings below. A unique `out/workflow-*` folder
keeps each run's candidates and logs; evidence from previous runs is retained.
Each generated candidate is checked against `out/probe.json`. Only a passing
candidate is copied to `out/summary.md`. A content rejection (checker exit
code 1) is sent back as feedback for the next attempt, for up to three
attempts. Model failures, timeouts, and checker file/input errors stop
immediately. Offline mode applies to the probe input, not model generation.

```mermaid
flowchart TD
    P[Run probe] --> J[out/probe.json]
    J --> PC[Probe check]
    PC -->|pass| G[Generate fresh summary candidate]
    PC -->|process or input error| STOP[Stop immediately]
    G --> SC[Summary check]
    SC -->|pass| PUB[Publish out/summary.md]
    SC -->|checker content rejection, up to 3 attempts| FB[Feed complete checker feedback]
    FB --> G
    SC -->|process or input error| STOP
    PUB --> PASS[Passing output]
```

Probe or checker process/input errors stop the workflow immediately. Only a
summary content rejection enters the bounded feedback loop; each retry uses a
fresh candidate and the previous checker's complete feedback.

The equivalent one-off generation command (the runner supplies a unique
candidate path and attempt-specific logs) uses:

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

The CLI writes the generated paragraph using `-o`, while
`course_summary` restricts the commands executed by the agent. The runner
checks the attempt candidate and publishes it only after validation succeeds.

Here, “offline” describes the saved weather input: `--offline` reads
`fixtures/met_hamar.json` without a live MET request. Generating a summary
still calls the configured model service. The summary permission profile
includes a read permission for the versioned NVM installation; that path
must match the Codex runtime installation used by the reader.

Prior headless runs used the `course_summary` permission profile and passed
the summary checker. The saved input has 83 entries from 3–13 October 2026,
with temperatures ranging from -0.3 °C to 16.6 °C.

On 2026-10-28, the deterministic suite passed all 28 tests. The actual
`./harness/run.sh --offline` execution completed with workflow exit code 0
and passed summary attempt 1. The published `out/summary.md` independently
passed its checker with exit code 0 and included the correct minimum
(-0.3 °C) and maximum (16.6 °C). Evidence is in
`out/workflow-20261028T065410Z-mTeyor`. No live MET request was made. Retry
and failure paths were exercised with stubs, not by this successful model run.

The summary checker verifies a 20–80 word count, a case-insensitive Hamar
mention, inclusion of the input minimum and maximum with °C, and that every
temperature stated with °C occurs in the probe input. It does not check the
summary’s historical/current framing, whether other claims are supported, or
that a generated summary was produced offline.

## W43 custom MCP forecast demo

Install the pinned optional MCP dependency from `requirements-mcp.txt` in
`.venv`, then start the demo from the repository root:

```sh
codex -c 'mcp_servers.met.enabled=true'
```

The `forecast(hours=24)` tool reads the saved fixture only and returns up to 24
historical forecast entries beginning at its first timestamp. These entries
are not current weather or observations; the parameter limits the number of
entries and does not guarantee a duration in hours. MET Norway data is provided
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

The MCP demo selects up to 24 usable entries. The existing workflow summary
uses all probe items. Run the complete test suite from a normal WSL shell with:

```sh
.venv/bin/python -m unittest discover -s tests
```

## GitHub Actions checks

The `checks` workflow runs on pull requests and pushes to `main`. Its single
Ubuntu 24.04 job installs the MCP requirements in `.venv`, confirms that the
MCP SDK imports, and runs these checks:

- `bash -n harness/run.sh`
- `./harness/run.sh --offline --dry-run`
- `./harness/run.sh --dry-run`
- `.venv/bin/python harness/probe.py --offline`
- `.venv/bin/python eval/check_probe.py`
- `.venv/bin/python -m unittest discover -s tests`
- `git diff --check`
- `git diff --exit-code -- fixtures/`

Reproduce the CI checks locally from the repository root with:

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements-mcp.txt
.venv/bin/python -c 'import mcp'
bash -n harness/run.sh
./harness/run.sh --offline --dry-run
./harness/run.sh --dry-run
.venv/bin/python harness/probe.py --offline
.venv/bin/python eval/check_probe.py
.venv/bin/python -m unittest discover -s tests
git diff --check
git diff --exit-code -- fixtures/
```

Here, offline means the probe uses the saved fixture and test inputs are
mocked. Installing dependencies still downloads packages.
