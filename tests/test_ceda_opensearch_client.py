import json
from unittest.mock import MagicMock, patch

import pytest
import requests
from typer.testing import CliRunner

from clients import ceda_opensearch_client as mod
from clients.ceda_opensearch_client import (
    CedaOpenSearchClient,
    CedaOpenSearchError,
)


def _response(json_data=None, text="", json_error=False):
    resp = MagicMock()
    resp.text = text
    if json_error:
        resp.json.side_effect = ValueError("bad")
    else:
        resp.json.return_value = json_data
    return resp


def test_search_maps_arguments_to_opensearch_parameters():
    with CedaOpenSearchClient(base_url="http://x/os/", timeout=3, verify=False) as c:
        c._session = MagicMock()
        c._session.get.return_value = _response({"features": []})
        result = c.search(query="sea", max_records=2, start_date="2020-01-01T00:00:00Z")
    assert result == {"features": []}
    args, kwargs = c._session.get.call_args
    assert args[0] == "http://x/os/request".replace("os/", "os/")
    assert kwargs["params"] == {
        "httpAccept": "application/geo+json",
        "query": "sea",
        "maximumRecords": 2,
        "startDate": "2020-01-01T00:00:00Z",
        "parentIdentifier": "cci",
    }
    assert kwargs["timeout"] == 3 and kwargs["verify"] is False


def test_search_atom_returns_raw_text():
    c = CedaOpenSearchClient(base_url="http://x")
    c._session = MagicMock()
    c._session.get.return_value = _response(text="<feed/>")
    assert c.search(response_format="atom") == "<feed/>"
    assert c._session.get.call_args.kwargs["params"]["httpAccept"] == (
        "application/atom+xml"
    )


def test_search_rejects_unknown_format():
    with pytest.raises(ValueError):
        CedaOpenSearchClient(base_url="http://x").search(response_format="csv")


def test_search_invalid_json_raises_client_error():
    c = CedaOpenSearchClient(base_url="http://x")
    c._session = MagicMock()
    c._session.get.return_value = _response(json_error=True)
    with pytest.raises(CedaOpenSearchError):
        c.search()


def test_description_returns_xml_text():
    c = CedaOpenSearchClient(base_url="http://x")
    c._session = MagicMock()
    c._session.get.return_value = _response(text="<xml/>")
    assert c.description() == "<xml/>"


def test_network_error_is_wrapped():
    c = CedaOpenSearchClient(base_url="http://x")
    c._session = MagicMock()
    c._session.get.side_effect = requests.ConnectionError("down")
    with pytest.raises(CedaOpenSearchError):
        c.description()


def test_defaults_come_from_settings():
    c = CedaOpenSearchClient()
    assert c.base_url.startswith("https://archive.opensearch.ceda.ac.uk")


def test_cli_prints_features():
    data = {"features": [{"properties": {"identifier": "abc", "title": "Sea"}}, {}]}
    with patch.object(mod.CedaOpenSearchClient, "search", return_value=data):
        result = CliRunner().invoke(mod.app, ["search", "sea"])
    assert result.exit_code == 0
    assert "abc" in result.output and "Sea" in result.output


def test_cli_reports_errors():
    with patch.object(
        mod.CedaOpenSearchClient, "search", side_effect=CedaOpenSearchError("boom")
    ):
        result = CliRunner().invoke(mod.app, ["search", "sea"])
    assert result.exit_code == 1


FILE_FEATURE = {
    "properties": {
        "title": "f.nc",
        "date": "d",
        "filesize": 1,
        "links": {
            "related": [
                {"title": "Download", "href": "http://dl"},
                {"title": "Opendap", "href": "http://od"},
            ]
        },
    }
}
FILE_ENTRY = {
    "title": "f.nc",
    "date": "d",
    "filesize": 1,
    "download": "http://dl",
    "opendap": "http://od",
}


def test_find_datasets_returns_uuid_and_title():
    data = {"features": [{"properties": {"identifier": "u1", "title": "T"}}]}
    c = CedaOpenSearchClient(base_url="http://x")
    with patch.object(c, "search", return_value=data) as s:
        assert c.find_datasets(
            "SOILMOISTURE", "2020-01-01T00:00:00Z", None, "1,2,3,4"
        ) == [{"uuid": "u1", "title": "T"}]
    assert s.call_args.kwargs["ecv"] == "SOILMOISTURE"
    assert s.call_args.kwargs["start_date"] == "2020-01-01T00:00:00Z"
    assert s.call_args.kwargs["bbox"] == "1,2,3,4"


def test_list_files_paginates_and_extracts_links():
    pages = [
        {"features": [FILE_FEATURE], "totalResults": 2},
        {"features": [FILE_FEATURE], "totalResults": 2},
    ]
    c = CedaOpenSearchClient(base_url="http://x")
    with patch.object(c, "search", side_effect=pages) as s:
        files = c.list_files("u1", "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
    assert files == [FILE_ENTRY, FILE_ENTRY]
    assert s.call_args_list[1].kwargs["start_record"] == 2
    assert s.call_args.kwargs["parent_identifier"] == "u1"


def test_list_files_stops_on_empty_page():
    c = CedaOpenSearchClient(base_url="http://x")
    with patch.object(c, "search", return_value={"features": []}):
        assert c.list_files("u1") == []


def _fake_xarray(lat_values):
    import xarray as xr

    ds = xr.Dataset(
        {"sm": (("lat", "lon"), [[1.0, 2.0], [3.0, 4.0]])},
        coords={"lat": lat_values, "lon": [10.0, 20.0]},
    )
    return patch("xarray.open_dataset", return_value=ds)


def test_open_subset_selects_nearest_point():
    with _fake_xarray([40.0, 50.0]):
        out = mod.open_subset("http://od", lat=49.0, lon=11.0)
    assert float(out["sm"]) == 3.0


def test_open_subset_selects_bbox_for_ascending_and_descending_lat():
    for lats in ([40.0, 50.0], [50.0, 40.0]):
        with _fake_xarray(lats):
            out = mod.open_subset("http://od", bbox=(5, 35, 15, 45))
        assert out["sm"].shape == (1, 1)


def test_open_subset_without_selection_returns_dataset():
    with _fake_xarray([40.0, 50.0]):
        assert "sm" in mod.open_subset("http://od")


def test_cli_datasets_and_files_print_rows():
    runner = CliRunner()
    with patch.object(
        mod.CedaOpenSearchClient,
        "find_datasets",
        return_value=[{"uuid": "u1", "title": "T"}],
    ):
        assert "u1\tT" in runner.invoke(mod.app, ["datasets", "SM"]).output
    with patch.object(
        mod.CedaOpenSearchClient, "list_files", return_value=[FILE_ENTRY]
    ):
        out = runner.invoke(mod.app, ["files", "u1"]).output
    assert "f.nc\thttp://od\thttp://dl" in out


def test_cli_datasets_and_files_report_errors():
    runner = CliRunner()
    err = CedaOpenSearchError("boom")
    with patch.object(mod.CedaOpenSearchClient, "find_datasets", side_effect=err):
        assert runner.invoke(mod.app, ["datasets", "SM"]).exit_code == 1
    with patch.object(mod.CedaOpenSearchClient, "list_files", side_effect=err):
        assert runner.invoke(mod.app, ["files", "u1"]).exit_code == 1


def test_cli_subset_prints_result_and_handles_errors():
    runner = CliRunner()
    with patch.object(mod, "open_subset") as sub:
        sub.return_value.load.return_value = "DATA"
        result = runner.invoke(mod.app, ["subset", "http://od", "--bbox", "1,2,3,4"])
    assert "DATA" in result.output and sub.call_args.args[3] == (1.0, 2.0, 3.0, 4.0)
    assert (
        runner.invoke(mod.app, ["subset", "http://od", "--bbox", "1,2"]).exit_code == 1
    )
    with patch.object(mod, "open_subset", side_effect=OSError("nope")):
        assert runner.invoke(mod.app, ["subset", "http://od"]).exit_code == 1


NOMINATIM = [
    {
        "display_name": "Roma, Italia",
        "lat": "41.9",
        "lon": "12.5",
        "boundingbox": ["41.8", "42.0", "12.4", "12.6"],
    }
]


def _geocode(payload=None, error=None, **kwargs):
    import asyncio

    resp = MagicMock()
    resp.json.return_value = payload
    with patch("clients.ceda_opensearch_client.requests.get") as get:
        if error:
            get.side_effect = error
        else:
            get.return_value = resp
        out = asyncio.run(mod.geocode_local("Rome", **kwargs))
    return json.loads(out), get


def test_geocode_local_returns_bbox_and_calls_nominatim():
    out, get = _geocode(NOMINATIM)
    assert out["bbox"] == "12.4,41.8,12.6,42.0"
    assert get.call_args.args[0] == mod.NOMINATIM_SEARCH_URL
    assert get.call_args.kwargs["params"]["q"] == "Rome"
    assert "User-Agent" in get.call_args.kwargs["headers"]


def test_geocode_local_applies_buffer_and_clamps():
    out, _ = _geocode(
        [{**NOMINATIM[0], "boundingbox": ["-89.9", "89.9", "-179.9", "179.9"]}],
        buffer_km=500,
    )
    assert out["bbox"] == "-180.0,-90.0,180.0,90.0"
    out, _ = _geocode(NOMINATIM, buffer_km=111)
    west, south, east, north = (float(v) for v in out["bbox"].split(","))
    assert south == pytest.approx(40.8) and north == pytest.approx(43.0)
    assert west < 12.4 and east > 12.6


def test_geocode_local_reports_no_results_and_http_errors():
    assert "No results" in _geocode([])[0]["error"]
    assert (
        "Geocoding failed" in _geocode(error=requests.ConnectionError("x"))[0]["error"]
    )


def test_cli_geocode_prints_bbox_or_fails():
    runner = CliRunner()
    ok = json.dumps({"bbox": "1,2,3,4"})
    with patch.object(mod, "geocode_local", return_value=ok):
        assert runner.invoke(mod.app, ["geocode", "Rome"]).output.strip() == "1,2,3,4"
    with patch.object(mod, "geocode_local", return_value=json.dumps({"error": "e"})):
        assert runner.invoke(mod.app, ["geocode", "Rome"]).exit_code == 1


def _pipeline_client(datasets=None, files=None):
    client = MagicMock()
    client.find_datasets.return_value = (
        [{"uuid": "u1", "title": "T"}] if datasets is None else datasets
    )
    client.list_files.return_value = [FILE_ENTRY] * 2 if files is None else files
    return client


def _time_ds(day):
    import xarray as xr

    return xr.Dataset({"sm": ("time", [1.0])}, coords={"time": [day]})


def test_run_pipeline_concatenates_subsets_over_time():
    client = _pipeline_client()
    with patch.object(mod, "open_subset") as sub:
        sub.return_value.load.side_effect = [_time_ds(1), _time_ds(2)]
        results = mod.run_pipeline(client, "SM", "s", "e", lat=1.0, lon=2.0)
    assert [r["uuid"] for r in results] == ["u1"]
    assert results[0]["data"].sizes["time"] == 2
    client.list_files.assert_called_once_with("u1", "s", "e", limit=5)
    assert sub.call_args.args == ("http://od", 1.0, 2.0, None)


def test_run_pipeline_iterates_all_datasets_and_skips_empty_ones():
    datasets = [{"uuid": f"u{i}", "title": f"T{i}"} for i in range(3)]
    client = _pipeline_client(datasets=datasets, files=[FILE_ENTRY])
    client.list_files.side_effect = [[FILE_ENTRY], [], [FILE_ENTRY]]
    with patch.object(mod, "open_subset") as sub:
        sub.return_value.load.return_value = "D"
        results = mod.run_pipeline(client, "SM", "s", "e")
    assert [r["uuid"] for r in results] == ["u0", "u2"]
    assert [c.args[0] for c in client.list_files.call_args_list] == ["u0", "u1", "u2"]


def test_run_pipeline_dataset_index_selects_single_dataset():
    datasets = [{"uuid": f"u{i}", "title": f"T{i}"} for i in range(3)]
    client = _pipeline_client(datasets=datasets, files=[FILE_ENTRY])
    with patch.object(mod, "open_subset") as sub:
        sub.return_value.load.return_value = "D"
        results = mod.run_pipeline(client, "SM", "s", "e", dataset_index=1)
    assert [r["uuid"] for r in results] == ["u1"]


def test_run_pipeline_single_file_and_explicit_dataset():
    client = _pipeline_client(files=[FILE_ENTRY])
    with patch.object(mod, "open_subset") as sub:
        sub.return_value.load.return_value = "ONE"
        results = mod.run_pipeline(client, "SM", "s", "e", dataset_uuid="u9")
    assert results == [{"uuid": "u9", "title": "u9", "data": "ONE"}]
    client.find_datasets.assert_not_called()


@pytest.mark.parametrize(
    "kwargs, message",
    [
        ({"datasets": []}, "No datasets"),
        ({"files": [{**FILE_ENTRY, "opendap": None}]}, "No OPeNDAP"),
    ],
)
def test_run_pipeline_errors(kwargs, message):
    with pytest.raises(CedaOpenSearchError, match=message):
        mod.run_pipeline(_pipeline_client(**kwargs), "SM", "s", "e")
    with pytest.raises(CedaOpenSearchError, match="dataset-index"):
        mod.run_pipeline(_pipeline_client(), "SM", "s", "e", dataset_index=5)


def test_cli_run_with_place_saves_output(tmp_path):
    ds = MagicMock()
    ds.__str__.return_value = "DATASET"
    results = [{"uuid": "u1", "title": "T", "data": ds}]
    geo = json.dumps({"bbox": "1,2,3,4"})
    out = tmp_path / "x.nc"
    args = ["run", "SM", "--start-date", "s", "--end-date", "e", "--place", "Rome"]
    with (
        patch.object(mod, "geocode_local", return_value=geo),
        patch.object(mod, "run_pipeline", return_value=results) as pipe,
    ):
        result = CliRunner().invoke(mod.app, [*args, "--output", str(out)])
    assert "DATASET" in result.output
    assert pipe.call_args.args[6] == (1.0, 2.0, 3.0, 4.0)
    ds.to_netcdf.assert_called_once_with(out)


def test_cli_run_validates_arguments_and_reports_errors():
    runner = CliRunner()
    base = ["run", "SM", "--start-date", "s", "--end-date", "e"]
    assert runner.invoke(mod.app, [*base, "--lat", "1"]).exit_code == 1
    assert runner.invoke(mod.app, [*base, "--bbox", "1,2"]).exit_code == 1
    err = json.dumps({"error": "x"})
    with patch.object(mod, "geocode_local", return_value=err):
        assert runner.invoke(mod.app, [*base, "--place", "Zz"]).exit_code == 1
    with patch.object(mod, "run_pipeline", side_effect=CedaOpenSearchError("b")):
        assert runner.invoke(mod.app, base).exit_code == 1


def test_cli_run_saves_one_file_per_dataset(tmp_path):
    results = [{"uuid": u, "title": "T", "data": MagicMock()} for u in ("u1", "u2")]
    args = ["run", "SM", "--start-date", "s", "--end-date", "e", "--bbox", "1,2,3,4"]
    with patch.object(mod, "run_pipeline", return_value=results):
        CliRunner().invoke(mod.app, [*args, "--output", str(tmp_path / "x.nc")])
    results[1]["data"].to_netcdf.assert_called_once_with(tmp_path / "x_u2.nc")


def test_list_files_limit_stops_paging_early():
    page = {"features": [FILE_FEATURE] * 2, "totalResults": 100}
    c = CedaOpenSearchClient(base_url="http://x")
    with patch.object(c, "search", return_value=page) as s:
        files = c.list_files("u1", limit=3)
    assert len(files) == 3
    assert s.call_count == 2
    assert s.call_args.kwargs["max_records"] == 3


def _write_nc(tmp_path):
    import xarray as xr

    path = tmp_path / "o.nc"
    xr.Dataset(
        {"sm": ("time", [0.1, 0.2])}, coords={"time": [0, 1]}, attrs={"k": 1}
    ).to_netcdf(path)
    return str(path)


def test_inspect_netcdf_summarises_and_samples_variables(tmp_path):
    out = mod.inspect_netcdf(_write_nc(tmp_path), ["sm", "missing"])
    assert out["dimensions"] == {"time": 2}
    assert out["variables"] == ["sm"] and out["attributes"] == {"k": "1"}
    assert out["data"] == {"sm": pytest.approx([0.1, 0.2])}
    assert "data" not in mod.inspect_netcdf(_write_nc(tmp_path))


def test_cli_inspect_netcdf_prints_json_or_fails(tmp_path):
    runner = CliRunner()
    ok = runner.invoke(
        mod.app, ["inspect-netcdf", _write_nc(tmp_path), "--variables", "sm"]
    )
    assert json.loads(ok.output)["data"]["sm"]
    bad = runner.invoke(mod.app, ["inspect-netcdf", str(tmp_path / "nope.nc")])
    assert bad.exit_code == 1
