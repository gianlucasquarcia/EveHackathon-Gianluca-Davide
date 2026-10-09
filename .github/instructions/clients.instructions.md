---
applyTo: "clients/**/*.py"
---

# Client guidelines
- Keep clients readable; separate pure logic (client class, pipeline, parsing) from Typer CLI commands so both the CLI and MCP tools can reuse it.
- Take base URLs and similar values (e.g. `CEDA_OPENSEARCH_URL`) from `settings`/environment, not hard-coded literals.
- Use a retrying session (429/5xx backoff), timeouts and context managers; raise `CedaOpenSearchError` with clear messages on HTTP errors.
- Keep `README.md` project layout in sync when adding a client.
