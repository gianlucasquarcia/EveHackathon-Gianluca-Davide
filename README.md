# FastMCP Server - Geospatial CEDA OpenSearch Client
![Python](https://img.shields.io/badge/python-3.10%20--%203.14-blue.svg)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![ty](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ty/main/assets/badge/v0.json)](https://github.com/astral-sh/ty)

A FastMCP server with a Typer CLI wrapper that exposes the CEDA archive (CCI) OpenSearch workflow as an MCP tool, plus a standalone client/CLI for the same pipeline.

## Features

- Exposes a `ceda_run` MCP tool that runs the four-phase CEDA pipeline: find the CCI datasets for an ECV, list their files for a date range, pick the OPeNDAP links, and read only a point or area remotely with xarray (netcdf4)
- `ceda_run` iterates over every matching dataset and returns, per dataset, its `uuid`, `title` and an `inspect` summary (dimensions, coordinates, variables, attributes), plus the data as JSON `records` (NaN as `null`, capped at 1000 rows, with a `truncated` flag)
- The area is given as `place` (geocoded with Nominatim), `bbox` (`west,south,east,north`) or `latitude` + `longitude`
- Adds titles, tags, and MCP annotations to the tool (read-only, idempotent, non-destructive, open-world)
- Includes a Typer CLI for starting the server with stdio or HTTP transport
- Uses environment-based settings for the default port, transport and the CEDA OpenSearch URL

## Project layout

- `mcp_server.py` — assembles the FastMCP server by mounting the tools sub-server
- `mcp_server_tools.py` — MCP tool definitions (`ceda_run`)
- `mcp_server_cli.py` — Typer CLI entry point (`run`, `list-tools` commands)
- `settings.py` — environment-backed configuration
- `clients/ceda_opensearch_client.py` — standalone client for the CEDA archive OpenSearch API (`CEDA_OPENSEARCH_URL`); workflow: `datasets SOILMOISTURE` (find dataset UUID) → `files <uuid> --start-date ... --end-date ...` (download + OPeNDAP links) → `subset <opendap_url> --lat 41.9 --lon 12.5` (remote point/`--bbox w,s,e,n` read with xarray/netcdf4); or all four in one go: `run SOILMOISTURE --start-date 2020-01-01T00:00:00Z --end-date 2020-01-05T23:59:59Z --place Rome [--output out.nc]`; also `search "sea surface"`, `geocode <place>` and `inspect-netcdf <file> --variables a,b` (summarise a saved NetCDF file). `run` handles all matching datasets by default; restrict with `--dataset-uuid` / `--dataset-index`, and cap files with `--max-files`. Run e.g. `uv run python clients/ceda_opensearch_client.py datasets SOILMOISTURE`
- `tests/test_mcp_server.py` — tests for the `ceda_run` tool and the server CLI commands
- `tests/test_ceda_opensearch_client.py` — mocked-network tests for the CEDA client, pipeline, geocoder and inspect helpers
- `.env.template` — template for local environment configuration
- `CONTRIBUTING.md` — contributor guide
- `SECURITY.md` — security policy and vulnerability reporting
- `.github/copilot-instructions.md` — repository-wide GitHub Copilot instructions
- `.github/instructions/*.instructions.md` — path-scoped Copilot instructions (tests, server, clients)
- `.github/prompts/*.prompt.md` — reusable Copilot prompts (`/add-mcp-tool`, `/review-changes`)

## Setup

Install dependencies with [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

Copy the environment template and adjust values as needed:

```bash
cp .env.template .env
```

The project metadata in `pyproject.toml` declares the dependencies:

- `fastmcp`
- `typer`
- `pytest`
- `requests`
- `xarray` and `netcdf4` (remote OPeNDAP subsetting)

## Configuration

Settings are read from environment variables. On startup, `settings.py` loads the
repository-local `.env` file when present; explicitly set environment variables take
precedence (see `settings.py` and `.env.template`):

- `MCP_SERVER_DEFAULT_PORT` (default: `8000`)
- `MCP_SERVER_DEFAULT_TRANSPORT` (default: `stdio`)
- `HTTP_REQUEST_TIMEOUT` (default: `10`) — seconds to wait for HTTP requests
- `HTTP_REQUEST_TLS_VERIFY` (default: `true`) — whether to verify HTTPS certificates
- `CEDA_OPENSEARCH_URL` (default: `https://archive.opensearch.ceda.ac.uk/opensearch`) — CEDA OpenSearch base URL

## Using uv

Run the server:

```bash
uv run mcp_server.py run
uv run mcp_server.py run --transport streamable-http --port 8000
```

Run the CEDA client:

```bash
uv run python clients/ceda_opensearch_client.py run SOILMOISTURE --start-date 2020-01-01T00:00:00Z --end-date 2020-01-05T23:59:59Z --place Rome
```

Run tests:

```bash
uv run coverage run -m pytest -v
uv run coverage report
```

Run the tests in `tests/` with `uv run python test.py` (extra arguments go to pytest, e.g. `-k ceda -x`).

Run the full test suite across Python 3.10–3.14 with [tox](https://tox.wiki/) (requires those interpreters to be installed and discoverable, e.g. via `py -0p`):

```bash
uv run tox
uv run tox -e py312  # run a single environment
```

Add a new dependency (updates `pyproject.toml` and `uv.lock`):

```bash
uv add <package>
```

## Run the server

Run in stdio mode (default):

```bash
uv run mcp_server.py run
```

Run in HTTP mode:

```bash
uv run mcp_server.py run --transport streamable-http --port 8000
```

The CLI defaults (`transport`, `port`) come from `settings.py`, which reads `MCP_SERVER_DEFAULT_TRANSPORT` and `MCP_SERVER_DEFAULT_PORT` from the environment.

## Run with Docker

Build the image:

```bash
docker build -t fastmcp-typer .
```

Run it (the image defaults to `streamable-http` transport on port 8000, bound to all interfaces via `FASTMCP_HOST=0.0.0.0`):

```bash
docker run --rm -p 8000:8000 fastmcp-typer
```

The server will be reachable at `http://localhost:8000/mcp`. Override settings with `-e`, e.g. `-e MCP_SERVER_DEFAULT_PORT=9000 -p 9000:9000`.

## List registered tools

```bash
uv run mcp_server.py list-tools
```

This calls the Typer `list_tools` command and prints the name, description, parameters, and output schema of each registered MCP tool.

## Run tests

```bash
uv run coverage run -m pytest -v
uv run coverage report
```

## FastMCP CLI

`fastmcp` also ships its own CLI (installed as part of the `fastmcp` dependency), which can inspect and run the server object directly without going through the project's Typer wrapper. Reference the server as `mcp_server.py:mcp` (module file plus the exported `FastMCP` instance).

Inspect the server (tools, prompts, resources, versions):

```bash
uv run fastmcp inspect mcp_server.py:mcp
```

Run the server directly with the FastMCP CLI:

```bash
uv run fastmcp run mcp_server.py:mcp --transport stdio
uv run fastmcp run mcp_server.py:mcp --transport http --port 8000
```

Display FastMCP version and environment info:

```bash
uv run fastmcp version
```

See `uv run fastmcp --help` for the full command list, including `call`, `dev`, and `install`.

## Notes

- `stdio` is used for local process-to-process MCP communication.
- `streamable-http` is used for HTTP-based MCP transport.
- The async tool (`ceda_run`) works without wrapping `mcp.run()` in `asyncio.run(...)`.
- `ceda_run` calls the public CEDA OpenSearch/OPeNDAP and Nominatim services and requires network access; the CEDA server rate-limits (HTTP 429), so the client retries with backoff.
- Run the CEDA client script with `uv run python clients/ceda_opensearch_client.py ...` from the repository root.

## Author
- Gianluca Squarcia ([@github](https://github.com/gianlucasquarcia))
- Davide Poveromo