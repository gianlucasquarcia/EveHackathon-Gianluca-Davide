# Copilot instructions

FastMCP server with a Typer CLI exposing the CEDA archive (CCI) OpenSearch/OPeNDAP workflow as the `ceda_run` tool, plus a standalone CEDA client. See `README.md` for the full layout.

## Stack
- Python >=3.10 (tested 3.10–3.14), managed with `uv` (`uv sync`); lockfile `uv.lock` is committed.
- FastMCP for the server, Typer for the CLI, pytest + coverage for tests, Ruff for lint/format, ty for type checking.

## Structure
- `mcp_server.py` only assembles the server by mounting the sub-server in `mcp_server_tools.py`.
- New tools go in `mcp_server_tools.py` (add `mcp_server_resources.py`/`mcp_server_prompts.py` and mount them if needed), not in `mcp_server.py`.
- `mcp_server_cli.py` is the Typer entry point; `settings.py` loads config from env vars / `.env`.
- `clients/ceda_opensearch_client.py` holds the CEDA client, pipeline, geocoder and CLI (run it with `uv run python clients/ceda_opensearch_client.py ...`); `tests/` holds pytest tests.

## Conventions
- Every tool needs a title, tags, and MCP annotations (read-only, idempotent, destructive, open-world hints).
- Config comes from `settings.py` and `.env.template`; add new variables to both. Never commit `.env` or secrets.
- Use type hints and docstrings on tools (they become the MCP tool description).
- Prefer async tools for I/O.

## Workflow
- Run tests: `uv run python -m pytest` (plain `pytest` cannot import `clients`); full matrix: `uv run tox`.
- Coverage must stay at 100% (`fail_under = 100` in `pyproject.toml`); add tests for every change.
- Lint/format with `uv run ruff check` and `uv run ruff format`; type check with `uv run ty check`.
- Add dependencies via `uv add <pkg>` so `pyproject.toml` and `uv.lock` stay in sync.
- Update `README.md` when adding or changing tools, settings, client commands, or layout.
