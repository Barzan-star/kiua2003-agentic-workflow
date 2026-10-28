import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from harness import mcp_met, probe


def sample_forecast():
    return {
        "properties": {
            "timeseries": [
                {
                    "time": (datetime(2026, 10, 27, tzinfo=timezone.utc) + timedelta(hours=hour)).isoformat().replace("+00:00", "Z"),
                    "data": {"instant": {"details": {"air_temperature": hour + 0.125}}},
                }
                for hour in range(30)
            ]
        }
    }


class ForecastDataTests(unittest.TestCase):
    def setUp(self):
        self.saved = sample_forecast()
        self.reader = patch.object(probe, "read_forecast", return_value=self.saved)
        self.reader.start()
        self.addCleanup(self.reader.stop)

    def test_entry_limit_is_clamped_to_one_through_twenty_four(self):
        self.assertEqual(len(mcp_met.forecast(0)), 1)
        self.assertEqual(len(mcp_met.forecast(999)), 24)

    def test_rows_preserve_source_values(self):
        self.assertEqual(
            mcp_met.forecast(1),
            [{"title": "Hamar forecast", "date": self.saved["properties"]["timeseries"][0]["time"], "temperature_c": 0.125}],
        )

    def test_limit_counts_usable_temperature_rows(self):
        data = sample_forecast()
        first = data["properties"]["timeseries"][0]
        del first["data"]["instant"]["details"]["air_temperature"]
        with patch.object(probe, "read_forecast", return_value=data):
            self.assertEqual(
                mcp_met.forecast(1),
                [{
                    "title": "Hamar forecast",
                    "date": data["properties"]["timeseries"][1]["time"],
                    "temperature_c": 1.125,
                }],
            )

    def test_missing_and_invalid_fixture_data_are_clear(self):
        with patch.object(probe, "read_forecast", side_effect=FileNotFoundError("fixture.json")):
            with self.assertRaisesRegex(ValueError, "Missing forecast fixture"):
                mcp_met.forecast()
        for bad in ({}, {"properties": {"timeseries": []}}):
            with self.subTest(bad=bad), patch.object(probe, "read_forecast", return_value=bad):
                with self.assertRaisesRegex(ValueError, "Invalid forecast fixture"):
                    mcp_met.forecast()

    def test_no_network_or_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = root / "fixture.json"
            fixture.write_text(json.dumps(self.saved), encoding="utf-8")
            original = fixture.read_bytes()
            before = sorted(str(path.relative_to(root)) for path in root.rglob("*"))
            self.reader.stop()
            with patch.object(probe, "FIXTURE", fixture), patch.object(
                probe, "urlopen", side_effect=AssertionError("network request")
            ) as request:
                self.assertEqual(len(mcp_met.forecast()), 24)
                request.assert_not_called()
            self.reader.start()
            self.assertEqual(fixture.read_bytes(), original)
            self.assertEqual(sorted(str(path.relative_to(root)) for path in root.rglob("*")), before)


try:
    from mcp import Client
except ImportError:
    Client = None


@unittest.skipIf(Client is None, "mcp SDK is not installed")
class MCPServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_discovery_and_successful_call(self):
        with patch.object(probe, "read_forecast", return_value=sample_forecast()):
            async with asyncio.timeout(5):
                async with Client(mcp_met.build_server(), mode="legacy") as client:
                    tools = await client.list_tools()
                    self.assertEqual([tool.name for tool in tools.tools], ["forecast"])
                    result = await client.call_tool("forecast", {"hours": 1})
                    self.assertFalse(result.is_error)
                    rendered = "".join(item.text for item in result.content if hasattr(item, "text"))
                    self.assertIn('"temperature_c": 0.125', rendered)

@unittest.skipIf(Client is None, "mcp SDK is not installed")
class MCPStdioServerTests(unittest.TestCase):
    def test_configured_stdio_launch_without_pythonpath(self):
        asyncio.run(self._run_client())

    async def _run_client(self):
        from mcp import StdioServerParameters

        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        parameters = StdioServerParameters(
            command=".venv/bin/python",
            args=["-m", "harness.mcp_met", "--offline"],
            env=env,
            cwd=Path(__file__).resolve().parents[1],
        )
        async with asyncio.timeout(20):
            async with Client(parameters, mode="legacy") as client:
                tools = await client.list_tools()
                self.assertEqual([tool.name for tool in tools.tools], ["forecast"])
                result = await client.call_tool("forecast", {"hours": 1})
                self.assertFalse(result.is_error)
                rendered = "".join(item.text for item in result.content if hasattr(item, "text"))
                self.assertIn('"temperature_c"', rendered)


if __name__ == "__main__":
    unittest.main()
