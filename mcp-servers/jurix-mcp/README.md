# Jurix MCP

HTTP-only Jurix MCP server with managed trial account pool, session reuse, and MCP tools.

## Run server

```bash
python my_server.py
```

By default the account/session SQLite database is stored in a single per-user global location instead of the current working directory:

- macOS: `~/Library/Application Support/jurixmcp/jurix.db`
- Linux: `${XDG_DATA_HOME:-~/.local/share}/jurixmcp/jurix.db`
- Windows: `%LOCALAPPDATA%\jurixmcp\jurix.db`

Override it explicitly with `JURIX_DB_PATH=/absolute/path/to/jurix.db`.

## MCP client smoke script

This script runs your requested flow through MCP tools:
1. Reuse an existing valid account if available (or create/confirm/login if missing)
2. Search Jurix titles with short keywords such as `kira sözleşmesi`
3. Download one found article as PDF

```bash
python scripts/mcp_client_smoke.py
```

Optional flags:

```bash
python scripts/mcp_client_smoke.py --server http://localhost:8000/mcp --query "kira sözleşmesi" --limit 5 --verbose
```

## Search guidance

- `jurix_search` is a keyword-based title search, not a natural-language search tool.
- Send 2-6 short Turkish keywords that are likely to appear in the article title.
- Avoid long questions, fact summaries, or paragraph-length prompts.
- If search/download responses are unexpectedly empty, call `jurix_pool_status` first and `jurix_ensure_pool` if the pool is unhealthy.
- Use `jurix_account_status` to inspect the currently selected account, or pass an email to inspect a specific stored account.
- Use `jurix_rotate_account` to switch away from the current account before a download; it creates a fresh trial account if no alternative is ready.

## Tests

```bash
pytest -q
pytest -q -m live
```
