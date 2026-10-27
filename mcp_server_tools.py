import asyncio
import json

import pandas as pd
from fastmcp import FastMCP

from clients.ceda_opensearch_client import (
    CedaOpenSearchClient,
    CedaOpenSearchError,
    geocode_local,
    inspect_dataset,
    run_pipeline,
)

mcp = FastMCP("Tools")

MAX_RESULT_ROWS = 1000


@mcp.tool(
    title="CEDA CCI data subset",
    description=(
        "Find a CEDA CCI dataset for an ECV (e.g. SOILMOISTURE), list its files for a "
        "date range and read only a point or area remotely via OPeNDAP."
    ),
    tags={"ceda", "cci", "opendap", "earth-observation", "external-api"},
    annotations={
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def ceda_run(
    ecv: str,
    start_date: str,
    end_date: str,
    place: str | None = None,
    bbox: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    dataset_uuid: str | None = None,
    dataset_index: int | None = None,
    max_files: int = 5,
) -> dict:
    """
    Run the four CEDA OpenSearch phases and return the subset as records.

    Args:
        ecv (str): ECV code, e.g. "SOILMOISTURE".
        start_date (str): ISO 8601 start, e.g. "2020-01-01T00:00:00Z".
        end_date (str): ISO 8601 end, e.g. "2020-01-05T23:59:59Z".
        place (str | None): Place name geocoded to a bbox (e.g. "Rome").
        bbox (str | None): "west,south,east,north".
        latitude (float | None): Point latitude (use with longitude).
        longitude (float | None): Point longitude (use with latitude).
        dataset_uuid (str | None): Skip the dataset search and use this UUID.
        dataset_index (int | None): Use only this matching dataset (default: all).
        max_files (int): Maximum number of files to read per dataset (default 5).

    Returns:
        dict: ``records`` (rows tagged with ``dataset_uuid``/``dataset_title``,
        capped at 1000 in total), ``datasets`` (uuid, title and an ``inspect``
        summary: dimensions, coordinates, variables, attributes), ``truncated``
        and ``bbox``.
    """
    chosen = sum(x is not None for x in (place, bbox, latitude))
    if chosen != 1 or (latitude is None) != (longitude is None):
        raise ValueError("Use exactly one of place, bbox, or latitude with longitude.")
    if place:
        geo = json.loads(await geocode_local(place, limit=1))
        if "error" in geo:
            raise ValueError(geo["error"])
        bbox = geo["bbox"]
    area = tuple(float(v) for v in bbox.split(",")) if bbox else None
    if area is not None and len(area) != 4:
        raise ValueError("bbox must be west,south,east,north")

    def _run():
        with CedaOpenSearchClient() as client:
            return run_pipeline(
                client,
                ecv,
                start_date,
                end_date,
                latitude,
                longitude,
                area,
                dataset_uuid,
                dataset_index,
                max_files,
            )

    try:
        results = await asyncio.to_thread(_run)
    except (CedaOpenSearchError, OSError, KeyError) as exc:
        raise ValueError(str(exc)) from exc
    frames = []
    for r in results:
        frame = r["data"].to_dataframe().reset_index()
        frame.insert(0, "dataset_title", r["title"])
        frame.insert(0, "dataset_uuid", r["uuid"])
        frames.append(frame)
    frame = pd.concat(frames, ignore_index=True)
    return {
        "bbox": bbox,
        "datasets": [
            {
                "uuid": r["uuid"],
                "title": r["title"],
                "inspect": inspect_dataset(r["data"]),
            }
            for r in results
        ],
        "truncated": len(frame) > MAX_RESULT_ROWS,
        "records": json.loads(frame.head(MAX_RESULT_ROWS).to_json(orient="records", date_format="iso")),
    }
