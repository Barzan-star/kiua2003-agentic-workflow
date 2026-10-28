#!/usr/bin/env python3
"""Fetch or read the cached MET Norway forecast for Hamar."""

import argparse
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import gzip
import json
import math
from pathlib import Path
import zlib
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "fixtures" / "met_hamar.json"
OUTPUT = ROOT / "out" / "probe.json"
CACHE = ROOT / "out" / "met_hamar_cache.json"
SOURCE_URL = (
    "https://api.met.no/weatherapi/locationforecast/2.0/compact"
    "?lat=60.7945&lon=11.0679"
)
USER_AGENT = (
    "kiua2003-agentic-workflow/0.1 "
    "(https://github.com/Barzan-star/kiua2003-agentic-workflow)"
)


def _valid_forecast(forecast):
    if not isinstance(forecast, dict):
        return False
    properties = forecast.get("properties")
    if not isinstance(properties, dict):
        return False
    timeseries = properties.get("timeseries")
    if not isinstance(timeseries, list):
        return False

    has_usable_entry = False
    for entry in timeseries:
        if not isinstance(entry, dict):
            return False
        timestamp = entry.get("time")
        if not isinstance(timestamp, str) or not timestamp:
            return False
        try:
            datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False

        data = entry.get("data")
        instant = data.get("instant") if isinstance(data, dict) else None
        details = instant.get("details") if isinstance(instant, dict) else None
        if not isinstance(details, dict):
            return False
        temperature = details.get("air_temperature")
        if temperature is None:
            continue
        if (
            isinstance(temperature, bool)
            or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)
        ):
            return False
        has_usable_entry = True
    return has_usable_entry


def _read_cache():
    if not CACHE.exists():
        return None
    try:
        entry = json.loads(CACHE.read_text(encoding="utf-8"))
        forecast = entry["forecast"]
        expires = entry.get("expires")
        last_modified = entry.get("last_modified")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError):
        return None

    if not _valid_forecast(forecast):
        return None
    if expires is not None and not isinstance(expires, str):
        return None
    if last_modified is not None and not isinstance(last_modified, str):
        return None
    return {"forecast": forecast, "expires": expires, "last_modified": last_modified}


def _is_unexpired(entry):
    if not entry["expires"]:
        return False
    try:
        expiry = parsedate_to_datetime(entry["expires"])
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return False
    return expiry > datetime.now(timezone.utc)


def _save_cache(forecast, expires, last_modified):
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps(
            {
                "forecast": forecast,
                "expires": expires,
                "last_modified": last_modified,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _response_header(headers, name):
    value = headers.get(name)
    return str(value) if value is not None else None


def _request_forecast(cache_entry):
    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Encoding": "gzip, deflate",
    }
    if cache_entry and cache_entry["last_modified"] is not None:
        headers["If-Modified-Since"] = cache_entry["last_modified"]
    request = Request(SOURCE_URL, headers=headers)

    try:
        response = urlopen(request, timeout=30)
    except HTTPError as error:
        if error.code != 304:
            raise RuntimeError(
                f"MET request failed: HTTP {error.code} {error.reason}"
            ) from error
        return _reuse_after_304(cache_entry, error.headers)
    except (URLError, OSError) as error:
        raise RuntimeError(f"MET request failed: {error}") from error

    with response:
        status = response.getcode()
        response_headers = response.headers
        if status == 304:
            return _reuse_after_304(cache_entry, response_headers)
        if status != 200:
            raise RuntimeError(f"MET request failed: unexpected HTTP status {status}")
        raw = response.read()
        content_encoding = response_headers.get("Content-Encoding", "identity")

    encoding = str(content_encoding).strip().lower()
    if encoding in ("", "identity"):
        pass
    elif encoding == "gzip":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as error:
            raise RuntimeError("MET response contained corrupt gzip data") from error
    elif encoding == "deflate":
        try:
            raw = zlib.decompress(raw)
        except zlib.error as error:
            raise RuntimeError("MET response contained corrupt deflate data") from error
    else:
        raise RuntimeError(f"MET response used unsupported content encoding: {encoding}")

    try:
        forecast = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RuntimeError("MET response contained invalid JSON") from error
    if not _valid_forecast(forecast):
        raise RuntimeError("MET response did not contain a valid forecast")

    _save_cache(
        forecast,
        _response_header(response_headers, "Expires"),
        _response_header(response_headers, "Last-Modified"),
    )
    return forecast


def _reuse_after_304(cache_entry, response_headers):
    if cache_entry is None:
        raise RuntimeError("MET returned HTTP 304 without a cached response")
    expires = _response_header(response_headers, "Expires")
    last_modified = _response_header(response_headers, "Last-Modified")
    _save_cache(
        cache_entry["forecast"],
        expires if expires is not None else cache_entry["expires"],
        last_modified if last_modified is not None else cache_entry["last_modified"],
    )
    return cache_entry["forecast"]


def read_forecast(offline):
    if offline:
        if not FIXTURE.exists():
            raise FileNotFoundError(
                f"Offline mode requires the saved fixture: {FIXTURE}"
            )
        return json.loads(FIXTURE.read_text(encoding="utf-8"))

    cache_entry = _read_cache()
    if cache_entry and _is_unexpired(cache_entry):
        return cache_entry["forecast"]
    return _request_forecast(cache_entry)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", help="use the saved fixture only"
    )
    args = parser.parse_args()

    try:
        forecast = read_forecast(args.offline)
    except (FileNotFoundError, RuntimeError, OSError, json.JSONDecodeError) as error:
        parser.error(str(error))

    items = []
    for entry in forecast["properties"]["timeseries"]:
        details = entry["data"]["instant"]["details"]
        temperature = details.get("air_temperature")
        if temperature is None:
            continue
        items.append(
            {
                "title": "",
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
