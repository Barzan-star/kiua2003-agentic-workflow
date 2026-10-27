#!/usr/bin/env python3
"""Check that a weather summary reflects the probe input."""

import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROBE = ROOT / "out" / "probe.json"
DEFAULT_SUMMARY = ROOT / "out" / "summary.md"
CELSIUS_TEMPERATURE = re.compile(
    r"(?<![\w.])([-+]?\d+(?:\.\d+)?)\s*°C", re.IGNORECASE
)


def _numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        return None
    return number if number.is_finite() else None


def _summary_temperatures(summary):
    values = []
    for match in CELSIUS_TEMPERATURE.finditer(summary):
        try:
            value = Decimal(match.group(1))
        except InvalidOperation:
            continue
        if value.is_finite():
            values.append(value)
    return values


def validate(probe_data, summary):
    """Return a list of validation errors without reading files."""
    errors = []
    words = summary.split()
    if not 20 <= len(words) <= 80:
        errors.append(f"summary must contain 20–80 words (found {len(words)})")
    if "hamar" not in summary.casefold():
        errors.append("summary must mention Hamar")

    try:
        items = probe_data["items"]
        temperatures = [
            value
            for item in items
            if isinstance(item, dict)
            if (value := _numeric(item.get("temperature_c"))) is not None
        ]
    except (KeyError, TypeError):
        temperatures = []

    summary_temperatures = _summary_temperatures(summary)
    if not temperatures:
        errors.append("probe input contains no usable temperatures")
    else:
        minimum, maximum = min(temperatures), max(temperatures)
        if minimum not in summary_temperatures:
            errors.append(f"summary must include the minimum temperature {minimum} °C")
        if maximum not in summary_temperatures:
            errors.append(f"summary must include the maximum temperature {maximum} °C")
        allowed = set(temperatures)
        for value in summary_temperatures:
            if value not in allowed:
                errors.append(f"summary includes temperature not present in probe input: {value} °C")

    return errors


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE, help="probe JSON path")
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY, help="summary Markdown path")
    args = parser.parse_args(argv)

    try:
        probe_data = json.loads(args.probe.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        parser.error(f"cannot read probe file {args.probe}: {error}")
    try:
        summary = args.summary.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        parser.error(f"cannot read summary file {args.summary}: {error}")

    errors = validate(probe_data, summary)
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
