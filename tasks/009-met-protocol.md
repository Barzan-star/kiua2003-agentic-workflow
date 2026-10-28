# Task 009: MET request protocol corrections

## Goal

Correct the live MET request coordinates and compression negotiation while
preserving the probe's offline fixture path, output format, and HTTP cache
semantics.

## Requirements

- Request latitude `60.7945` and longitude `11.0679`.
- Advertise gzip and standard HTTP deflate compression and decode either with
  Python's standard library. Continue accepting identity/uncompressed bodies.
- Reject unsupported content encodings and corrupt compressed bodies before
  saving a refreshed cache entry or writing new probe output.
- Retain urllib redirect handling, the identifying User-Agent, and existing
  Expires, Last-Modified, and HTTP 304 behavior.
- Preserve fixture-only offline operation, fixture bytes, and output JSON
  schema.
- Briefly document the live request changes in README.md.

## Focused regression coverage

- Assert request coordinates, User-Agent, and compression headers.
- Accept valid gzip, zlib-wrapped HTTP deflate, and uncompressed responses.
- Reject corrupt compressed data and unsupported encodings, preserving the
  prior cache and probe output.
- Mock all HTTP responses; preserve existing test coverage.

## Acceptance checks

```sh
python3 -m unittest discover -s tests -p 'test_probe_cache.py'
python3 harness/probe.py --offline && python3 eval/check_probe.py
git diff --check
git diff --exit-code HEAD -- eval/ fixtures/ harness/run.sh .codex/config.toml
```

## Verification results (2026-10-28)

- The regression tests exposed the previous longitude precision and missing
  compression handling. After the fix, all 11 focused cache tests and all 37
  full-suite tests passed.
- The offline probe and checker, whitespace check, and protected-path diff
  check passed.
- Task 009 commit `906f973` passed GitHub CI run `40666992808`. HTTP responses
  were mocked. Live MET requests and schedules remain untested.
