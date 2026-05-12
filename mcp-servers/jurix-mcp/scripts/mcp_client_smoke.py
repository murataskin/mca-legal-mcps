import argparse
import asyncio
import json
import logging
from typing import Any

from fastmcp import Client


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def extract_payload(result: Any) -> Any:
    if hasattr(result, "content") and result.content:
        first = result.content[0]
        if hasattr(first, "text"):
            return json.loads(first.text)
    return result


async def run_flow(server_url: str, query: str, limit: int) -> None:
    client = Client(server_url)

    async with client:
        logging.info("Ensuring account pool (reuse existing account if valid; otherwise create one)")
        pool_result = await client.call_tool("jurix_ensure_pool", {})
        logging.info("Pool response: %s", extract_payload(pool_result))

        logging.info("Searching query: %s", query)
        search_result = await client.call_tool("jurix_search", {"query": query, "limit": limit})
        search_payload = extract_payload(search_result)

        if not isinstance(search_payload, dict):
            raise RuntimeError(f"Unexpected jurix_search payload: {search_payload!r}")
        logging.info("Search response: %s", search_payload)

        articles = search_payload.get("results") or []
        if not articles:
            raise RuntimeError(f"Search returned no articles. Follow-up: {search_payload.get('next_actions')}")

        selected = next((a for a in articles if a.get("id")), None)
        if not selected:
            raise RuntimeError("Search results contain no downloadable article id")

        article_id = str(selected["id"])
        logging.info("Selected article id=%s title=%s", article_id, selected.get("title"))

        logging.info("Downloading article as PDF")
        download_result = await client.call_tool("jurix_download_pdf", {"article_id": article_id})
        payload = extract_payload(download_result)

        logging.info("Download completed")
        logging.info("Result: %s", payload)
        print(json.dumps(payload, ensure_ascii=False, indent=2))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "MCP client smoke script: ensure account/login, keyword-search Jurix titles, and download an article PDF."
        )
    )
    parser.add_argument("--server", default="http://localhost:8000/mcp", help="MCP server URL")
    parser.add_argument("--query", default="kira tespit", help="Short Jurix title keywords, not a natural-language prompt")
    parser.add_argument("--limit", type=int, default=5, help="Max results to inspect")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(args.verbose)
    await run_flow(args.server, args.query, args.limit)


if __name__ == "__main__":
    asyncio.run(main())
