#!/usr/bin/env python3
"""Offline MCP demonstration for the saved Hamar forecast fixture."""

import argparse
import json

from harness import probe


TOOL_DESCRIPTION = (
    "Return up to the requested number of saved historical forecast entries, "
    "starting at the fixture's first timestamp. These are not current weather "
    "or observations. The hours parameter limits entries, not a guaranteed duration."
)


def forecast(hours=24):
    """Return compact rows from the saved offline forecast fixture."""
    try:
        data = probe.read_forecast(offline=True)
    except FileNotFoundError as error:
        raise ValueError(f"Missing forecast fixture: {error}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"Could not read forecast fixture: {error}") from error

    if not probe._valid_forecast(data):
        raise ValueError("Invalid forecast fixture: expected usable MET timeseries data")

    count = max(1, min(24, int(hours)))
    rows = []
    for entry in data["properties"]["timeseries"]:
        temperature = entry["data"]["instant"]["details"].get("air_temperature")
        if temperature is None:
            continue
        rows.append(
            {
                "title": "Hamar forecast",
                "date": entry["time"],
                "temperature_c": temperature,
            }
        )
        if len(rows) >= count:
            break
    if not rows:
        raise ValueError("Invalid forecast fixture: selected entries have no temperatures")
    return rows


def build_server():
    """Build the single-tool MCP server; keep SDK imports optional for data tests."""
    from mcp.server.mcpserver import MCPServer
    from mcp.types import ToolAnnotations

    server = MCPServer(name="met-forecast-demo", version="1.0.0")

    @server.tool(
        name="forecast",
        description=TOOL_DESCRIPTION,
        annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
    )
    async def forecast_tool(hours: int = 24):
        return forecast(hours)

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true", required=True,
        help="use only the saved fixture (the only supported mode)",
    )
    parser.parse_args()
    build_server().run("stdio")


if __name__ == "__main__":
    main()
