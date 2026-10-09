---
applyTo: "tests/**/*.py"
---

# Test guidelines
- Use pytest with plain `test_*` functions; name tests after behavior (`test_ceda_run_truncates_large_results`).
- Call tool functions directly, or via the FastMCP server for end-to-end checks; use `typer.testing.CliRunner` for CLI commands.
- Never hit the network: mock `requests`, CEDA/Nominatim, and OPeNDAP/xarray access.
- Keep 100% coverage (see `pyproject.toml`); cover error paths and edge cases.
- Run with `uv run python -m pytest`. CEDA client tests live in `tests/test_ceda_opensearch_client.py`.
