import json
import gzip
from urllib.parse import parse_qs, urlparse
import zlib
from datetime import datetime, timedelta, timezone
from email.message import Message
from email.utils import format_datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from harness import probe


def forecast_at(temperature=6.5):
    return {
        "properties": {
            "timeseries": [
                {
                    "time": "2026-10-27T12:00:00Z",
                    "data": {
                        "instant": {"details": {"air_temperature": temperature}}
                    },
                }
            ]
        }
    }


def http_date(delta):
    return format_datetime(datetime.now(timezone.utc) + delta, usegmt=True)


class FakeResponse:
    def __init__(self, status, body=b"", headers=None):
        self.status = status
        self.body = body
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.body


class ProbeCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        root = Path(self.temp_dir.name)
        self.fixture = root / "fixtures" / "met_hamar.json"
        self.output = root / "out" / "probe.json"
        self.cache = root / "out" / "met_hamar_cache.json"
        self.fixture.parent.mkdir(parents=True)
        self.fixture.write_text(json.dumps(forecast_at()), encoding="utf-8")
        self.paths = (
            patch.object(probe, "FIXTURE", self.fixture),
            patch.object(probe, "OUTPUT", self.output),
            patch.object(probe, "CACHE", self.cache),
        )
        for path_patch in self.paths:
            path_patch.start()
            self.addCleanup(path_patch.stop)

    def write_cache(self, forecast=None, expires=None, last_modified=None):
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.cache.write_text(
            json.dumps(
                {
                    "forecast": forecast or forecast_at(),
                    "expires": expires,
                    "last_modified": last_modified,
                }
            ),
            encoding="utf-8",
        )

    def test_offline_reads_fixture_without_network_or_fixture_changes(self):
        original = self.fixture.read_bytes()
        with patch.object(probe, "urlopen", side_effect=AssertionError("network")) as call:
            self.assertEqual(probe.read_forecast(offline=True), forecast_at())
            call.assert_not_called()
        self.assertEqual(self.fixture.read_bytes(), original)

    def test_unexpired_cache_is_reused_without_network(self):
        saved = forecast_at(7.25)
        self.write_cache(saved, http_date(timedelta(hours=1)), "Wed, 21 Oct 2015 07:28:00 GMT")
        with patch.object(probe, "urlopen", side_effect=AssertionError("network")) as call:
            self.assertEqual(probe.read_forecast(offline=False), saved)
            call.assert_not_called()

    def test_200_refresh_saves_body_and_metadata_and_sends_exact_validator(self):
        last_modified = "Wed, 21 Oct 2015 07:28:00 GMT"
        self.write_cache(forecast_at(1.0), http_date(timedelta(hours=-1)), last_modified)
        refreshed = forecast_at(8.0)
        expires = http_date(timedelta(hours=2))
        response = FakeResponse(
            200,
            json.dumps(refreshed).encode("utf-8"),
            {"Expires": expires, "Last-Modified": last_modified},
        )
        with patch.object(probe, "urlopen", return_value=response) as call:
            self.assertEqual(probe.read_forecast(offline=False), refreshed)
        request = call.call_args.args[0]
        self.assertEqual(parse_qs(urlparse(request.full_url).query), {"lat": ["60.7945"], "lon": ["11.0679"]})
        self.assertEqual(request.get_header("Accept-encoding"), "gzip, deflate")
        self.assertEqual(request.get_header("If-modified-since"), last_modified)
        self.assertEqual(request.get_header("User-agent"), probe.USER_AGENT)
        saved = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(saved["forecast"], refreshed)
        self.assertEqual(saved["expires"], expires)
        self.assertEqual(saved["last_modified"], last_modified)

    def test_compressed_and_uncompressed_200_responses_are_accepted(self):
        forecast = forecast_at(8.25)
        body = json.dumps(forecast).encode("utf-8")
        cases = (
            ("gzip", gzip.compress(body)),
            ("deflate", zlib.compress(body)),
            (None, body),
        )
        for encoding, response_body in cases:
            with self.subTest(encoding=encoding):
                self.cache.unlink(missing_ok=True)
                headers = {"Content-Encoding": encoding} if encoding else {}
                with patch.object(
                    probe,
                    "urlopen",
                    return_value=FakeResponse(200, response_body, headers),
                ):
                    self.assertEqual(probe.read_forecast(offline=False), forecast)

    def test_bad_encoding_responses_preserve_cache_and_output(self):
        self.write_cache(forecast_at(2.0), http_date(timedelta(hours=-1)))
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text("previous output\n", encoding="utf-8")
        original_cache = self.cache.read_bytes()
        original_output = self.output.read_bytes()
        cases = (
            ("gzip", b"not gzip data"),
            ("deflate", b"not deflate data"),
            ("br", b"opaque body"),
        )
        for encoding, body in cases:
            with self.subTest(encoding=encoding):
                response = FakeResponse(
                    200,
                    body,
                    {"Content-Encoding": encoding},
                )
                with patch.object(probe, "urlopen", return_value=response):
                    with patch("sys.argv", ["probe.py"]):
                        with self.assertRaises(SystemExit) as error:
                            probe.main()
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(self.cache.read_bytes(), original_cache)
                self.assertEqual(self.output.read_bytes(), original_output)

    def test_304_reuses_response_and_updates_provided_metadata(self):
        saved_forecast = forecast_at(4.0)
        old_expiry = http_date(timedelta(hours=-1))
        last_modified = "Wed, 21 Oct 2015 07:28:00 GMT"
        self.write_cache(saved_forecast, old_expiry, last_modified)
        new_expiry = http_date(timedelta(hours=3))
        headers = Message()
        headers["Expires"] = new_expiry
        error = HTTPError(probe.SOURCE_URL, 304, "Not Modified", headers, None)
        with patch.object(probe, "urlopen", side_effect=error) as call:
            self.assertEqual(probe.read_forecast(offline=False), saved_forecast)
        request = call.call_args.args[0]
        self.assertEqual(request.get_header("If-modified-since"), last_modified)
        saved = json.loads(self.cache.read_text(encoding="utf-8"))
        self.assertEqual(saved["forecast"], saved_forecast)
        self.assertEqual(saved["expires"], new_expiry)
        self.assertEqual(saved["last_modified"], last_modified)

    def test_missing_or_invalid_cache_triggers_refresh(self):
        response_body = json.dumps(forecast_at()).encode("utf-8")
        for invalid in (False, True):
            with self.subTest(invalid=invalid):
                if invalid:
                    self.cache.write_text("not json", encoding="utf-8")
                else:
                    self.cache.unlink(missing_ok=True)
                response = FakeResponse(200, response_body, {"Expires": http_date(timedelta(hours=1))})
                with patch.object(probe, "urlopen", return_value=response) as call:
                    self.assertEqual(probe.read_forecast(offline=False), forecast_at())
                    call.assert_called_once()

    def test_unexpired_structurally_invalid_cache_triggers_refresh(self):
        invalid = {
            "properties": {
                "timeseries": [{"time": "2026-10-27T12:00:00Z", "data": {}}]
            }
        }
        self.write_cache(invalid, http_date(timedelta(hours=1)))
        refreshed = forecast_at(9.0)
        response = FakeResponse(
            200,
            json.dumps(refreshed).encode("utf-8"),
            {"Expires": http_date(timedelta(hours=1))},
        )
        with patch.object(probe, "urlopen", return_value=response) as call:
            self.assertEqual(probe.read_forecast(offline=False), refreshed)
            call.assert_called_once()

    def test_empty_unexpired_cache_triggers_refresh(self):
        self.write_cache({"properties": {"timeseries": []}}, http_date(timedelta(hours=1)))
        refreshed = forecast_at(10.0)
        response = FakeResponse(
            200,
            json.dumps(refreshed).encode("utf-8"),
            {"Expires": http_date(timedelta(hours=1))},
        )
        with patch.object(probe, "urlopen", return_value=response) as call:
            self.assertEqual(probe.read_forecast(offline=False), refreshed)
            call.assert_called_once()

    def test_invalid_200_fails_and_preserves_cache_and_output(self):
        self.write_cache(forecast_at(), http_date(timedelta(hours=-1)))
        original_cache = self.cache.read_bytes()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text("previous output\n", encoding="utf-8")
        original_output = self.output.read_bytes()
        response = FakeResponse(
            200,
            json.dumps({"properties": {"timeseries": []}}).encode("utf-8"),
            {"Expires": http_date(timedelta(hours=1))},
        )
        with patch.object(probe, "urlopen", return_value=response):
            with patch("sys.argv", ["probe.py"]):
                with self.assertRaises(SystemExit) as error:
                    probe.main()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.cache.read_bytes(), original_cache)
        self.assertEqual(self.output.read_bytes(), original_output)

    def test_request_failure_through_main_preserves_output_and_expired_cache(self):
        old_expiry = http_date(timedelta(hours=-1))
        self.write_cache(forecast_at(), old_expiry, "Wed, 21 Oct 2015 07:28:00 GMT")
        original_cache = self.cache.read_bytes()
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text("previous output\n", encoding="utf-8")
        original_output = self.output.read_bytes()
        with patch.object(probe, "urlopen", side_effect=URLError("offline")):
            with patch("sys.argv", ["probe.py"]):
                with self.assertRaises(SystemExit) as error:
                    probe.main()
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(self.cache.read_bytes(), original_cache)
        self.assertEqual(self.output.read_bytes(), original_output)


if __name__ == "__main__":
    unittest.main()
