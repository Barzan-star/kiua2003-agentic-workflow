# Task 001: Probe MET Norway forecast for Hamar

## Goal
Fetch a small public weather forecast for Hamar from MET Norway and produce a checkable JSON output.

## Context
- Source: MET Norway Locationforecast 2.0 compact API
- Documentation: https://api.met.no/weatherapi/locationforecast/2.0/documentation
- Terms: https://api.met.no/doc/TermsOfService
- Location: Hamar, Norway
- Use approximately lat=60.7945 and lon=11.06798
- Output file: out/probe.json
- Save fetched source data in fixtures/met_hamar.json for reproducible/offline use.

## Constraints
- Do not edit anything in eval/
- Public data only; no personal data
- Python 3 standard library only
- Send an identifying User-Agent
- Avoid unnecessary requests and reuse saved data where practical
- UTF-8 throughout

## Output
out/probe.json must contain:
- source_url: the HTTPS MET Norway API URL used
- items: at least one item
- each item has:
  - title: non-empty text
  - date: ISO-formatted forecast timestamp
  - temperature_c: numeric temperature in Celsius

## Acceptance
All must pass:
- `python3 harness/probe.py && python3 eval/check_probe.py` prints PASS
- `python3 harness/probe.py --offline && python3 eval/check_probe.py` prints PASS
- eval/check_probe.py was committed and failed before implementation began

## Out of scope
- Summarisation
- Scheduling
- LLM-generated weather interpretation
- User interface
