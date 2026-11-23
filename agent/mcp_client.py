"""Client for the policy MCP server (streamable HTTP).

The MCP server is not behind the API gateway, it has its own url (MCP_SERVER_URL).
A new connection is opened for every search; the chat is interactive so this is fast enough
and we do not have to keep an async session open next to the sync code.
"""

import asyncio
import json

from mcp import Client

TOOL_NAME = "search_tuition_policies"


class PolicySearchError(Exception):
    pass


class PolicySearchClient:
    def __init__(self, url, timeout: float = 20.0):
        # url is normally the MCP_SERVER_URL string; the tests pass an in-process server object
        self.url = url
        self.timeout = timeout

    def search(self, query: str, top_k: int | None = None) -> dict:
        arguments = {"query": query}
        if top_k:
            arguments["top_k"] = top_k
        try:
            return asyncio.run(self._call(arguments))
        except PolicySearchError:
            raise
        except Exception as exc:  # connection refused, timeout, protocol error ...
            raise PolicySearchError(f"MCP server {self.url} is not reachable: {_short_error(exc)}") from exc

    async def _call(self, arguments: dict) -> dict:
        async with Client(self.url, read_timeout_seconds=self.timeout) as client:
            result = await client.call_tool(TOOL_NAME, arguments)
        text = "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")
        if result.is_error:
            raise PolicySearchError(text or "policy search failed")
        if isinstance(result.structured_content, dict):
            return result.structured_content
        try:
            return json.loads(text)
        except ValueError:
            return {"matches": [], "raw": text}


def _short_error(exc: BaseException) -> str:
    # anyio wraps errors from the task group in an ExceptionGroup
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"
