#!/usr/bin/env bash
set -euo pipefail

offline=false
dry_run=false

for arg in "$@"; do
  case "$arg" in
    --offline) offline=true ;;
    --dry-run) dry_run=true ;;
    *)
      printf 'Error: unknown argument: %s\n' "$arg" >&2
      printf 'Usage: %s [--offline] [--dry-run]\n' "$0" >&2
      exit 2
      ;;
  esac
done

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"
if [[ "$offline" == true ]]; then
  probe_input='fixtures/met_hamar.json'
else
  probe_input='out/met_hamar_cache.json (when valid) or MET API'
fi

if [[ "$dry_run" == true ]]; then
  printf 'DRY RUN: no stages, checks, model calls, network requests, or files will be created.\n\n'
  printf 'Stage 1: probe\n  Input:  %s\n  Output: out/probe.json\n  Check:  eval/check_probe.py\n\n' "$probe_input"
  printf 'Stage 2: check probe\n  Input:  out/probe.json\n  Output: PASS or failure\n  Check:  python3 eval/check_probe.py\n\n'
  printf 'Stage 3: generate and check summary (up to 3 attempts)\n'
  printf '  Input:  out/probe.json and harness/prompts/summarise.md\n'
  printf '  Output: unique out/workflow-*/summary-attempt-N.md; publish passing candidate to out/summary.md\n'
  printf '  Check:  python3 eval/check_summary.py --probe out/probe.json --summary <candidate>\n'
  printf '  Model:  timeout --kill-after=5s 90s codex exec --strict-config --ephemeral --json -m gpt-6-luna\n'
  printf '          model_reasoning_effort=low, default_permissions=course_summary, approval_policy=never\n'
  printf '          web_search=disabled, agents.enabled=false\n'
  printf '  Retry:  checker exit 1 only; pass complete checker feedback to next attempt\n'
  exit 0
fi

cd "$repo_root"
out_dir="$repo_root/out"
mkdir -p "$out_dir"
run_dir="$(mktemp -d "$out_dir/workflow-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")"

printf 'Running probe; evidence: %s\n' "$run_dir"
if [[ "$offline" == true ]]; then
  python3 harness/probe.py --offline >"$run_dir/probe.stdout.log" 2>"$run_dir/probe.stderr.log"
else
  python3 harness/probe.py >"$run_dir/probe.stdout.log" 2>"$run_dir/probe.stderr.log"
fi
python3 eval/check_probe.py >"$run_dir/probe-check.log" 2>&1

for attempt in 1 2 3; do
  candidate="$run_dir/summary-attempt-$attempt.md"
  events="$run_dir/summary-attempt-$attempt.events.jsonl"
  stderr_log="$run_dir/summary-attempt-$attempt.stderr.log"
  prompt_input="$run_dir/summary-attempt-$attempt.prompt.md"
  feedback="$run_dir/summary-attempt-$attempt.check.log"

  cat harness/prompts/summarise.md > "$prompt_input"
  if (( attempt > 1 )); then
    printf '\n\nChecker feedback from the previous candidate (address every item):\n' >> "$prompt_input"
    cat "$run_dir/summary-attempt-$((attempt - 1)).check.log" >> "$prompt_input"
  fi

  printf 'Generating summary attempt %s/3\n' "$attempt"
  timeout --kill-after=5s 90s codex exec \
    --strict-config --ephemeral --json \
    -m gpt-6-luna \
    -c 'model_reasoning_effort="low"' \
    -c 'default_permissions="course_summary"' \
    -c 'approval_policy="never"' \
    -c 'web_search="disabled"' \
    -c 'agents.enabled=false' \
    -o "$candidate" - \
    < "$prompt_input" \
    > "$events" \
    2> "$stderr_log"

  set +e
  python3 eval/check_summary.py --probe out/probe.json --summary "$candidate" > "$feedback" 2>&1
  checker_status=$?
  set -e

  if (( checker_status == 0 )); then
    cp -- "$candidate" "$out_dir/summary.md"
    printf 'Summary passed validation and was published to out/summary.md\n'
    exit 0
  fi

  if (( checker_status != 1 )); then
    cat "$feedback" >&2
    printf 'Error: summary checker failed with exit code %s; see %s\n' "$checker_status" "$feedback" >&2
    exit "$checker_status"
  fi

  cat "$feedback"
  if (( attempt == 3 )); then
    printf 'Error: all three summary candidates were rejected; see %s\n' "$run_dir" >&2
    exit 1
  fi
done
