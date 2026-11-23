"""PolicySearchClient against a small in-process MCP server (same tool shape as mcp-server)."""

import pytest
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from mcp_client import PolicySearchClient, PolicySearchError


def make_server():
    server = MCPServer("test-policies")

    @server.tool(name="search_tuition_policies")
    def search_tuition_policies(query: str, top_k: int = 3) -> dict:
        if query == "boom":
            raise ToolError("index is not loaded")
        matches = [{"section": "2.1", "heading": "Fall term", "text": "September 30, 2026", "score": 0.9}]
        return {"document": "University Tuition Policies", "documentId": "UNI-TUITION-2026-01",
                "query": query, "matches": matches[:top_k]}

    return server


def test_search_returns_matches():
    result = PolicySearchClient(make_server()).search("payment deadline", top_k=2)

    assert result["query"] == "payment deadline"
    assert result["matches"][0]["section"] == "2.1"


def test_tool_error_becomes_policy_search_error():
    with pytest.raises(PolicySearchError, match="index is not loaded"):
        PolicySearchClient(make_server()).search("boom")


def test_unreachable_server():
    with pytest.raises(PolicySearchError, match="not reachable"):
        PolicySearchClient("http://127.0.0.1:9/mcp", timeout=3).search("deadline")
