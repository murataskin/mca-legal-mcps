import asyncio
import json
from fastmcp import Client

client = Client("http://localhost:8000/mcp")


async def call_search() -> None:
    async with client:
        result = await client.call_tool("jurix_search", {"query": "is hukuku", "limit": 3})
        payload = result
        if hasattr(result, "content") and result.content and hasattr(result.content[0], "text"):
            payload = json.loads(result.content[0].text)
        print(payload)


if __name__ == "__main__":
    asyncio.run(call_search())
