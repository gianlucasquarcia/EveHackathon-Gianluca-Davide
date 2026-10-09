"""Client for the CEDA archive OpenSearch API.

Based on https://archive.opensearch.ceda.ac.uk/opensearch/description.xml
"""

import asyncio
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import requests
import typer
import xarray as xr
from requests.adapters import HTTPAdapter
from typing_extensions import Self
from urllib3 import Retry

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from settings import settings

NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT", "geocode-mcp/0.1 (agentic-eo-hackathon)"
)
TIMEOUT = 60

# Parameter names accepted by the "results" endpoint, keyed by Python argument.
_PARAM_NAMES = {
    "uuid": "uuid",
    "query": "query",
    "max_records": "maximumRecords",
    "start_page": "startPage",
    "start_record": "startRecord",
    "start_date": "startDate",
    "end_date": "endDate",
    "parent_identifier": "parentIdentifier",
    "bbox": "bbox",
    "ecv": "ecv",
    "frequency": "frequency",
    "institute": "institute",
    "processing_level": "processingLevel",
    "product_string": "productString",
    "product_version": "productVersion",
    "project": "project",
    "data_type": "dataType",
    "sensor": "sensor",
    "platform": "platform",
    "file_format": "fileFormat",
    "drs_id": "drsId",
}

_FORMATS = {
    "geojson": "application/geo+json",
    "atom": "application/atom+xml",
}


class CedaOpenSearchError(Exception):
    """Raised when the CEDA OpenSearch service cannot be queried."""


class CedaOpenSearchClient:
    """Thin wrapper around the CEDA OpenSearch ``request`` and ``description.xml`` endpoints."""

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int | None = None,
        verify: bool | None = None,
    ) -> None:
        self.base_url = (base_url or settings.CEDA_OPENSEARCH_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.HTTP_REQUEST_TIMEOUT
        self.verify = verify if verify is not None else settings.HTTP_REQUEST_TLS_VERIFY
        self._session = requests.Session()
        retry = Retry(
            total=5,
            backoff_factor=1,
            status_forcelist=[429, 502, 503, 504],
            allowed_methods=["GET"],
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session.mount("http://", HTTPAdapter(max_retries=retry))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self._session.close()

    def _get(self, path: str, params: dict[str, Any]) -> requests.Response:
        url = f"{self.base_url}/{path}"
        try:
            response = self._session.get(
                url, params=params, timeout=self.timeout, verify=self.verify
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise CedaOpenSearchError(f"Request to {url} failed: {exc}") from exc
        return response

    def description(self) -> str:
        """Return the raw OpenSearch description document (XML)."""
        return self._get("description.xml", {}).text

    def search(
        self,
        *,
        response_format: str = "geojson",
        uuid: str | None = None,
        query: str | None = None,
        max_records: int | None = None,
        start_page: int | None = None,
        start_record: int | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        parent_identifier: str | None = "cci",
        bbox: str | None = None,
        ecv: str | None = None,
        frequency: str | None = None,
        institute: str | None = None,
        processing_level: str | None = None,
        product_string: str | None = None,
        product_version: str | None = None,
        project: str | None = None,
        data_type: str | None = None,
        sensor: str | None = None,
        platform: str | None = None,
        file_format: str | None = None,
        drs_id: str | None = None,
    ) -> dict[str, Any] | str:
        """Search the archive.

        Dates are ISO 8601 (e.g. ``2020-01-01T00:00:00Z``); ``bbox`` is
        ``west,south,east,north``. Returns parsed GeoJSON for ``geojson``
        or the raw Atom XML text for ``atom``.
        """
        if response_format not in _FORMATS:
            raise ValueError(
                f"response_format must be one of {sorted(_FORMATS)}, got {response_format!r}"
            )
        values = {
            "uuid": uuid,
            "query": query,
            "max_records": max_records,
            "start_page": start_page,
            "start_record": start_record,
            "start_date": start_date,
            "end_date": end_date,
            "parent_identifier": parent_identifier,
            "bbox": bbox,
            "ecv": ecv,
            "frequency": frequency,
            "institute": institute,
            "processing_level": processing_level,
            "product_string": product_string,
            "product_version": product_version,
            "project": project,
            "data_type": data_type,
            "sensor": sensor,
            "platform": platform,
            "file_format": file_format,
            "drs_id": drs_id,
        }
        params: dict[str, Any] = {"httpAccept": _FORMATS[response_format]}
        params.update({_PARAM_NAMES[k]: v for k, v in values.items() if v is not None})
        response = self._get("request", params)
        if response_format == "atom":
            return response.text
        try:
            return response.json()
        except ValueError as exc:
            raise CedaOpenSearchError("Response was not valid JSON") from exc

    def find_datasets(
        self,
        ecv: str,
        start_date: str | None = None,
        end_date: str | None = None,
        bbox: str | None = None,
    ) -> list[dict[str, Any]]:
        """Phase 1: list the CCI datasets (uuid + title) for an ECV code."""
        result = self.search(
            parent_identifier="cci",
            ecv=ecv,
            start_date=start_date,
            end_date=end_date,
            bbox=bbox,
            max_records=100,
        )
        return [
            {"uuid": f["properties"]["identifier"], "title": f["properties"]["title"]}
            for f in result.get("features", [])
        ]

    def list_files(
        self,
        dataset_uuid: str,
        start_date: str | None = None,
        end_date: str | None = None,
        page_size: int = 100,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Phase 2/3: list the files of a dataset with download and OPeNDAP links.

        ``limit`` stops paging once that many files are collected.
        """
        files: list[dict[str, Any]] = []
        start_record = 1
        while True:
            result = self.search(
                parent_identifier=dataset_uuid,
                start_date=start_date,
                end_date=end_date,
                max_records=page_size if limit is None else min(page_size, limit),
                start_record=start_record,
            )
            features = result.get("features", [])
            files.extend(_file_entry(f) for f in features)
            start_record += len(features)
            if (
                not features
                or start_record > result.get("totalResults", 0)
                or (limit is not None and len(files) >= limit)
            ):
                return files[:limit]


def _file_entry(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties", {})
    links = {
        link.get("title", "").lower(): link.get("href")
        for link in props.get("links", {}).get("related", [])
    }
    return {
        "title": props.get("title"),
        "date": props.get("date"),
        "filesize": props.get("filesize"),
        "download": links.get("download"),
        "opendap": links.get("opendap"),
    }


def open_subset(
    opendap_url: str,
    lat: float | None = None,
    lon: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
):
    """Phase 4: lazily open a remote file via OPeNDAP and select a point or area.

    ``bbox`` is (west, south, east, north). Only the selected data is
    transferred when the result is loaded (e.g. ``.load()``).
    """

    ds = xr.open_dataset(opendap_url, engine="netcdf4")
    if lat is not None and lon is not None:
        return ds.sel(lat=lat, lon=lon, method="nearest")
    if bbox is not None:
        west, south, east, north = bbox
        lats = ds["lat"]
        lat_slice = slice(south, north) if lats[0] < lats[-1] else slice(north, south)
        return ds.sel(lat=lat_slice, lon=slice(west, east))
    return ds


app = typer.Typer(help="Search the CEDA archive via OpenSearch.")


@app.command()
def search(
    query: str | None = typer.Argument(None, help="Free-text search terms."),
    max_records: int = typer.Option(10, help="Maximum records to return."),
    start_date: str | None = typer.Option(None, help="ISO 8601 start date."),
    end_date: str | None = typer.Option(None, help="ISO 8601 end date."),
    bbox: str | None = typer.Option(None, help="west,south,east,north"),
    ecv: str | None = typer.Option(None, help="Essential climate variable code."),
    project: str | None = typer.Option(None, help="Project filter."),
) -> None:
    """Print title and id of matching records."""
    try:
        with CedaOpenSearchClient() as client:
            result = client.search(
                parent_identifier="cci",
                query=query,
                max_records=max_records,
                start_date=start_date,
                end_date=end_date,
                bbox=bbox,
                ecv=ecv,
                project=project,
            )
    except CedaOpenSearchError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for feature in result.get("features", []):
        props = feature.get("properties", {})
        # typer.echo(
        #     f"{props.get('identifier', '-')}\t{props.get('title', '')}"
        #     f"\t{props.get('date', '')}"
        # )
        print(json.dumps(props, indent=2))
    typer.echo(f"Total results: {result.get('totalResults', 0)}", err=True)


@app.command()
def datasets(
    ecv: str = typer.Argument(..., help="ECV code, e.g. SOILMOISTURE."),
    start_date: str | None = typer.Option(None, help="e.g. 2020-01-01T00:00:00Z"),
    end_date: str | None = typer.Option(None, help="e.g. 2020-01-31T23:59:59Z"),
    bbox: str | None = typer.Option(None, help="west,south,east,north"),
) -> None:
    """Phase 1: find the datasets (uuid + title) for an ECV."""
    try:
        with CedaOpenSearchClient() as client:
            found = client.find_datasets(ecv, start_date, end_date, bbox)
    except CedaOpenSearchError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for d in found:
        typer.echo(f"{d['uuid']}\t{d['title']}")


@app.command()
def files(
    dataset_uuid: str = typer.Argument(..., help="Dataset UUID from `datasets`."),
    start_date: str | None = typer.Option(None, help="e.g. 2020-01-01T00:00:00Z"),
    end_date: str | None = typer.Option(None, help="e.g. 2020-01-31T23:59:59Z"),
) -> None:
    """Phases 2-3: list files with their download and OPeNDAP links."""
    try:
        with CedaOpenSearchClient() as client:
            found = client.list_files(dataset_uuid, start_date, end_date)
    except CedaOpenSearchError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for f in found:
        typer.echo(f"{f['title']}\t{f['opendap']}\t{f['download']}")


@app.command()
def subset(
    opendap_url: str = typer.Argument(..., help="OPeNDAP link from `files`."),
    lat: float | None = typer.Option(None, help="Point latitude."),
    lon: float | None = typer.Option(None, help="Point longitude."),
    bbox: str | None = typer.Option(None, help="west,south,east,north"),
) -> None:
    """Phase 4: read only a point or area remotely via OPeNDAP + xarray."""
    area = tuple(float(v) for v in bbox.split(",")) if bbox else None
    if area is not None and len(area) != 4:
        typer.echo("Error: --bbox needs west,south,east,north", err=True)
        raise typer.Exit(1)
    try:
        typer.echo(open_subset(opendap_url, lat, lon, area).load())
    except (OSError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = os.getenv(
    "NOMINATIM_USER_AGENT", "geocode-mcp/0.1 (agentic-eo-hackathon)"
)


async def _http_get(
    url: str,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> requests.Response:
    """Run a blocking requests call in a worker thread."""

    def _call() -> requests.Response:
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=settings.HTTP_REQUEST_TIMEOUT,
            verify=settings.HTTP_REQUEST_TLS_VERIFY,
        )
        response.raise_for_status()
        return response

    return await asyncio.to_thread(_call)


def run_pipeline(
    client: CedaOpenSearchClient,
    ecv: str,
    start_date: str,
    end_date: str,
    lat: float | None = None,
    lon: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    dataset_uuid: str | None = None,
    dataset_index: int | None = None,
    max_files: int = 5,
) -> list[dict[str, Any]]:
    """Run phases 1-4 over every matching dataset.

    Returns one ``{"uuid", "title", "data"}`` entry per dataset that has files in
    the date range, where ``data`` is an xarray Dataset concatenated over time.
    ``dataset_uuid`` or ``dataset_index`` restrict the run to a single dataset.
    """

    if dataset_uuid is not None:
        found = [{"uuid": dataset_uuid, "title": dataset_uuid}]
    else:
        found = client.find_datasets(ecv, start_date, end_date)
        if not found:
            raise CedaOpenSearchError(f"No datasets found for ECV {ecv}")
        if dataset_index is not None:
            if not 0 <= dataset_index < len(found):
                raise CedaOpenSearchError(
                    f"--dataset-index must be between 0 and {len(found) - 1}"
                )
            found = [found[dataset_index]]

    results = []
    for dataset in found:
        entries = [
            f
            for f in client.list_files(
                dataset["uuid"], start_date, end_date, limit=max_files
            )
            if f["opendap"]
        ]
        if not entries:
            continue
        parts = [
            open_subset(f["opendap"], lat, lon, bbox).load()
            for f in entries[:max_files]
        ]
        data = xr.concat(parts, dim="time") if len(parts) > 1 else parts[0]
        results.append(
            {"uuid": dataset["uuid"], "title": dataset["title"], "data": data}
        )
    if not results:
        raise CedaOpenSearchError(
            f"No OPeNDAP files for ECV {ecv} between {start_date} and {end_date}"
        )
    return results


@app.command()
def run(
    ecv: str = typer.Argument(..., help="ECV code, e.g. SOILMOISTURE."),
    start_date: str = typer.Option(..., help="e.g. 2020-01-01T00:00:00Z"),
    end_date: str = typer.Option(..., help="e.g. 2020-01-05T23:59:59Z"),
    place: str | None = typer.Option(None, help="Place name to geocode into a bbox."),
    bbox: str | None = typer.Option(None, help="west,south,east,north"),
    lat: float | None = typer.Option(None, help="Point latitude."),
    lon: float | None = typer.Option(None, help="Point longitude."),
    dataset_uuid: str | None = typer.Option(None, help="Skip phase 1 search."),
    dataset_index: int | None = typer.Option(
        None, help="Use only this dataset of phase 1 (default: all)."
    ),
    max_files: int = typer.Option(5, help="Maximum files per dataset."),
    output: str | None = typer.Option(None, help="Save the result as NetCDF."),
) -> None:
    """Run all four phases: find dataset, list files, pick OPeNDAP, subset."""
    if sum(x is not None for x in (place, bbox, lat)) > 1 or (
        (lat is None) != (lon is None)
    ):
        typer.echo(
            "Error: use exactly one of --place, --bbox or --lat with --lon", err=True
        )
        raise typer.Exit(1)
    if place:
        geo = json.loads(asyncio.run(geocode_local(place, limit=1)))
        if "error" in geo:
            typer.echo(f"Error: {geo['error']}", err=True)
            raise typer.Exit(1)
        bbox = geo["bbox"]
    area = tuple(float(v) for v in bbox.split(",")) if bbox else None
    if area is not None and len(area) != 4:
        typer.echo("Error: --bbox needs west,south,east,north", err=True)
        raise typer.Exit(1)
    try:
        with CedaOpenSearchClient() as client:
            results = run_pipeline(
                client,
                ecv,
                start_date,
                end_date,
                lat,
                lon,
                area,
                dataset_uuid,
                dataset_index,
                max_files,
            )
    except (CedaOpenSearchError, OSError, KeyError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc
    for r in results:
        typer.echo(f"=== {r['uuid']}\t{r['title']}")
        if output:
            path = Path(output)
            if len(results) > 1:
                path = path.with_name(f"{path.stem}_{r['uuid']}{path.suffix}")
            r["data"].to_netcdf(path)
            typer.echo(f"Saved {path}", err=True)
        typer.echo(r["data"])


async def geocode_local(
    place_name: str,
    buffer_km: float = 0.0,
    limit: int = 5,
) -> str:
    """
    Convert a place name to a bounding box.

    Geocodes a place name (city, region, country, landmark, etc.) into a
    bounding box string in "west,south,east,north" format: the same format
    accepted by get_effis_burnt_areas and other tools.

    Uses the OpenStreetMap Nominatim API (free, no API key required).

    Args:
        place_name: Name of the place to geocode (e.g. "Greece",
                    "Athens", "Evia island", "Peloponnese").
        buffer_km:  Optional buffer in km to expand the bbox (default 0).
        limit:      Maximum number of candidate results to return (default 5).

    Returns:
        JSON with the top result's bbox string (ready to pass to other tools)
        and all candidate matches.
    """

    try:
        resp = await _http_get(
            NOMINATIM_SEARCH_URL,
            params={
                "q": place_name,
                "format": "json",
                "limit": str(limit),
                "addressdetails": "1",
            },
            headers={"User-Agent": NOMINATIM_USER_AGENT},
        )
        results = resp.json()
    except (requests.RequestException, ValueError) as exc:
        return json.dumps({"error": f"Geocoding failed: {exc}"})

    if not results:
        return json.dumps(
            {
                "error": f"No results found for '{place_name}'.",
                "place_name": place_name,
            }
        )

    candidates = []
    for r in results:
        south, north, west, east = (float(v) for v in r["boundingbox"])
        if buffer_km:
            dlat = buffer_km / 111.0
            dlon = buffer_km / (
                111.0 * max(math.cos(math.radians((south + north) / 2)), 0.01)
            )
            south, north = max(south - dlat, -90.0), min(north + dlat, 90.0)
            west, east = max(west - dlon, -180.0), min(east + dlon, 180.0)
        candidates.append(
            {
                "display_name": r.get("display_name"),
                "lat": float(r["lat"]),
                "lon": float(r["lon"]),
                "bbox": f"{west},{south},{east},{north}",
            }
        )
    return json.dumps(
        {
            "place_name": place_name,
            "bbox": candidates[0]["bbox"],
            "candidates": candidates,
        }
    )


@app.command()
def geocode(
    place_name: str = typer.Argument(..., help="e.g. Italy, Rome."),
    buffer_km: float = typer.Option(0.0, help="Expand the bbox by this many km."),
    limit: int = typer.Option(5, help="Maximum candidates."),
) -> None:
    """Convert a place name to a west,south,east,north bbox (Nominatim)."""
    out = json.loads(asyncio.run(geocode_local(place_name, buffer_km, limit)))
    if "error" in out:
        typer.echo(f"Error: {out['error']}", err=True)
        raise typer.Exit(1)
    typer.echo(out["bbox"])


def inspect_dataset(ds, variables: list[str] | None = None) -> dict:
    """Summarise an xarray Dataset; optionally include values of some variables."""
    summary = {
        "dimensions": dict(ds.sizes),
        "coordinates": list(ds.coords.keys()),
        "variables": list(ds.data_vars.keys()),
        "attributes": {k: str(v) for k, v in ds.attrs.items()},
    }
    if variables:
        summary["data"] = {
            var: ds[var].values.tolist() for var in variables if var in ds
        }
    return summary


def inspect_netcdf(nc_file_path: str, variables: list[str] | None = None) -> dict:
    """Open a NetCDF file and return its summary and selected variable values."""

    with xr.open_dataset(nc_file_path) as ds:
        return inspect_dataset(ds, variables)


@app.command("inspect-netcdf")
def inspect_netcdf_command(
    nc_file_path: str = typer.Argument(..., help="Path of a NetCDF file."),
    variables: str | None = typer.Option(None, help="Comma-separated variables."),
) -> None:
    """Print a JSON summary of a NetCDF file (e.g. one saved by `run --output`)."""
    names = [v for v in variables.split(",") if v] if variables else None
    try:
        typer.echo(json.dumps(inspect_netcdf(nc_file_path, names), indent=2))
    except (OSError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from exc


if __name__ == "__main__":
    sys.exit(app())
