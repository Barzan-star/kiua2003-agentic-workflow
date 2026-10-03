#!/usr/bin/env python3
"""Fetch or read the cached MET Norway forecast for Hamar."""

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "met_hamar.json"
OUTPUT = ROOT / "out" / "probe.json"
SOURCE_URL = (
    "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    "?lat=60.7945&lon=11.06798"
)
USER_AGENT = "kiua2003-agentic-workflow/0.1"


def read_forecast(offline):
    if FIXTURE.exists():
        return json.loads(FIXTURE.read_text(encoding="utf-8"))
    if offline:
        raise FileNotFoundError(
            f"Offline mode requires the saved fixture: {FIXTURE}"
        )

    request = Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=30) as response:
        raw = response.read()
    forecast = json.loads(raw.decode("utf-8"))
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(
        json.dumps(forecast, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return forecast


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="use the saved fixture only"
    )
    args = parser.parse_args()

    forecast = read_forecast(args.offline)
    items = []
    for entry in forecast["properties"]["timeseries"]:
        details = entry["data"]["instant"]["details"]
        temperature = details.get("air_temperature")
        if temperature is None:
            continue
        items.append(
            {
                "title": "Hamar forecast",
                "date": entry["time"],
                "temperature_c": temperature,
            }
        )

    if not items:
        raise ValueError("The forecast contains no air temperature entries")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"source_url": SOURCE_URL, "items": items}, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
