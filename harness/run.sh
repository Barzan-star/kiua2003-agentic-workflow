#!/usr/bin/env bash
set -euo pipefail

offline=false
dry_run=false

for arg in "$@"; do
  case "$arg" in
    --offline)
      offline=true
      ;;
    --dry-run)
      dry_run=true
      ;;
    *)
      printf 'Error: unknown argument: %s\n' "$arg" >&2
      printf 'Usage: %s [--offline] --dry-run\n' "$0" >&2
      exit 2
      ;;
  esac
done

if [[ "$offline" == true ]]; then
  probe_input='fixtures/met_hamar.json'
else
  probe_input='out/met_hamar_cache.json (when valid) or MET API'
fi

if [[ "$dry_run" != true ]]; then
  printf 'Error: actual execution is not implemented yet; use --dry-run to preview the workflow.\n' >&2
  exit 1
fi

printf 'DRY RUN: no stages, checks, model calls, or network requests will run.\n'
printf '\n'
printf 'Stage 1: probe\n'
printf '  Input:  %s\n' "$probe_input"
printf '  Output: out/probe.json\n'
printf '  Check:  eval/check_probe.py\n'
printf '\n'
printf 'Stage 2: summarise [PLANNED — not implemented yet]\n'
printf '  Input:  out/probe.json\n'
printf '  Output: out/summary.md\n'
printf '  Check:  eval/check_summary.py\n'
