---
applyTo: "mcp_server*.py,settings.py"
---

# MCP server guidelines
- Define tools in `mcp_server_tools.py` (add resource/prompt modules only if needed); `mcp_server.py` only mounts them.
- Every `@mcp.tool` sets `title`, `description`, `tags`, and `annotations` (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`); set `openWorldHint` true for external services.
- Use Google-style docstrings (Args/Returns) and full type hints.
- Use `async def` for I/O or waiting; read config from `settings`, never `os.environ` directly.
- New settings: add to `settings.py` and `.env.template`, and document in `README.md`.
