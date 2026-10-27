import asyncio
import json

import pytest
from fastmcp import Client
from typer.testing import CliRunner

import mcp_server
import mcp_server_cli
import mcp_server_tools

runner = CliRunner()


def test_run_command_uses_stdio_by_default(monkeypatch):
    calls = {}

    def fake_run(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr(mcp_server.mcp, "run", fake_run)

    result = runner.invoke(mcp_server.mcp_typer, ["run"])

    assert result.exit_code == 0
    assert calls == {"args": (), "kwargs": {}}


def test_run_command_uses_http_transport_when_requested(monkeypatch):
    calls = {}

    def fake_run(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs

    monkeypatch.setattr(mcp_server.mcp, "run", fake_run)

    result = runner.invoke(mcp_server.mcp_typer, ["run", "--transport", "http", "--port", "9001"])

    assert result.exit_code == 0
    assert calls == {
        "args": (),
        "kwargs": {"transport": "streamable-http", "port": 9001},
    }


def test_cli_list_tools_prints_tool_metadata(monkeypatch, capsys):
    class FakeTool:
        def __init__(self):
            self.name = "example"
            self.title = "Example"
            self.description = "Example tool"
            self.tags = {"example", "test"}
            self.annotations = {"readOnlyHint": True}
            self.parameters = {"type": "object"}
            self.output_schema = {"type": "string"}

    class FakeMcp:
        async def list_tools(self):
            return [FakeTool()]

    monkeypatch.setattr(mcp_server, "mcp", FakeMcp())

    asyncio.run(mcp_server_cli.list_mcp_tools())

    output = capsys.readouterr().out
    assert "Tool: example" in output
    assert "Title: Example" in output
    assert "Description: Example tool" in output
    assert "Tags: example, test" in output
    assert "Annotations: {'readOnlyHint': True}" in output
    assert "Parameters:" in output
    assert "Output Schema:" in output


def test_cli_list_tools_command(monkeypatch):
    calls = []

    def fake_run(coroutine):
        calls.append(coroutine)
        coroutine.close()

    monkeypatch.setattr(mcp_server_cli.asyncio, "run", fake_run)

    result = runner.invoke(mcp_server_cli.mcp_typer, ["list-tools"])

    assert result.exit_code == 0
    assert len(calls) == 1


def _ceda_ds():
    import xarray as xr

    return xr.Dataset(
        {"sm": ("time", [float("nan"), 0.3])},
        coords={"time": [0, 1], "lat": 41.9},
    )


def _call_ceda(monkeypatch, ds=None, geo=None, **kwargs):
    from unittest.mock import MagicMock

    results = [{"uuid": "u1", "title": "T", "data": ds or _ceda_ds()}]
    pipeline = MagicMock(return_value=results)
    monkeypatch.setattr(mcp_server_tools, "run_pipeline", pipeline)
    monkeypatch.setattr(mcp_server_tools, "CedaOpenSearchClient", MagicMock())

    async def fake_geocode(*_args, **_kwargs):
        return json.dumps(geo or {"bbox": "1,2,3,4"})

    monkeypatch.setattr(mcp_server_tools, "geocode_local", fake_geocode)
    args = {"ecv": "SM", "start_date": "s", "end_date": "e", **kwargs}
    return asyncio.run(mcp_server_tools.ceda_run(**args)), pipeline


def test_ceda_run_returns_records_with_nan_as_null(monkeypatch):
    result, pipeline = _call_ceda(monkeypatch, latitude=41.9, longitude=12.5)

    inspect = result["datasets"][0].pop("inspect")
    assert inspect["variables"] == ["sm"] and inspect["dimensions"] == {"time": 2}
    assert result["datasets"] == [{"uuid": "u1", "title": "T"}]
    assert result["records"][0]["dataset_uuid"] == "u1"
    assert result["records"][0]["sm"] is None
    assert result["records"][1]["sm"] == 0.3
    assert result["truncated"] is False
    assert pipeline.call_args.args[4:7] == (41.9, 12.5, None)


def test_ceda_run_geocodes_place_to_bbox(monkeypatch):
    result, pipeline = _call_ceda(monkeypatch, place="Rome")

    assert result["bbox"] == "1,2,3,4"
    assert pipeline.call_args.args[6] == (1.0, 2.0, 3.0, 4.0)


def test_ceda_run_truncates_large_results(monkeypatch):
    monkeypatch.setattr(mcp_server_tools, "MAX_RESULT_ROWS", 1)

    result, _ = _call_ceda(monkeypatch, bbox="1,2,3,4")

    assert result["truncated"] is True
    assert len(result["records"]) == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"latitude": 1.0},
        {"place": "x", "bbox": "1,2,3,4"},
        {"bbox": "1,2"},
    ],
)
def test_ceda_run_rejects_invalid_area(monkeypatch, kwargs):
    with pytest.raises(ValueError):
        _call_ceda(monkeypatch, **kwargs)


def test_ceda_run_reports_geocoding_and_pipeline_errors(monkeypatch):
    with pytest.raises(ValueError, match="nope"):
        _call_ceda(monkeypatch, geo={"error": "nope"}, place="x")

    from clients.ceda_opensearch_client import CedaOpenSearchError

    def boom(*_a, **_k):
        raise CedaOpenSearchError("down")

    monkeypatch.setattr(mcp_server_tools, "run_pipeline", boom)
    with pytest.raises(ValueError, match="down"):
        asyncio.run(
            mcp_server_tools.ceda_run("SM", "s", "e", bbox="1,2,3,4"),
        )


def test_ceda_run_tool_metadata():
    tools = asyncio.run(mcp_server.mcp.list_tools())

    assert [t.name for t in tools] == ["ceda_run"]
    annotations = tools[0].annotations
    assert tools[0].title and tools[0].tags
    assert annotations is not None
    assert annotations.read_only_hint is True
    assert annotations.open_world_hint is True


def test_ceda_run_is_listed_as_mcp_tool():
    async def run():
        async with Client(mcp_server.mcp) as client:
            return [t.name for t in await client.list_tools()]

    assert "ceda_run" in asyncio.run(run())
