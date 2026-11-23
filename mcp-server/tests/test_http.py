"""End-to-end test over real streamable HTTP.

Starts the server with uvicorn on a free local port in a background thread and
calls the tool with the MCP client, the same way the agent does.
"""

import socket
import threading
import time

import httpx2
import pytest
import uvicorn

from mcp import Client

import server

pytestmark = pytest.mark.anyio

AZURE_HOST = "tuition-mcp-test.azurewebsites.net"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def base_url():
    mp = pytest.MonkeyPatch()
    mp.setenv("MCP_ALLOWED_HOSTS", AZURE_HOST)
    mp.setenv("MCP_STATELESS", "true")
    options = server.run_options()
    mp.undo()

    port = free_port()
    app = server.mcp.streamable_http_app(
        streamable_http_path=options["streamable_http_path"],
        stateless_http=options["stateless_http"],
        transport_security=options["transport_security"],
        host="127.0.0.1",
    )
    uv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if uv.started:
            break
        time.sleep(0.05)
    assert uv.started, "server did not start"

    yield f"http://127.0.0.1:{port}"

    uv.should_exit = True
    thread.join(timeout=5)


async def test_client_calls_tool_over_http(base_url):
    async with Client(f"{base_url}/mcp") as client:
        tools = (await client.list_tools()).tools
        assert [t.name for t in tools] == ["search_tuition_policies"]

        result = await client.call_tool(
            "search_tuition_policies", {"query": "refund for early withdrawal", "top_k": 2}
        )
    assert not result.is_error
    data = result.structured_content
    assert data["documentId"] == "UNI-TUITION-2026-01"
    assert data["matches"][0]["section"] == "6.1"
    assert len(data["matches"]) == 2


async def test_empty_query_over_http(base_url):
    async with Client(f"{base_url}/mcp") as client:
        result = await client.call_tool("search_tuition_policies", {"query": ""})
    assert result.is_error
    assert "query must not be empty" in result.content[0].text


def test_health_endpoint(base_url):
    r = httpx2.get(f"{base_url}/health")
    assert r.status_code == 200
    assert r.json()["sections"] == 25


INIT_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "1"},
    },
}
HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_unknown_host_header_is_rejected(base_url):
    r = httpx2.post(f"{base_url}/mcp", json=INIT_BODY, headers={**HEADERS, "Host": "evil.example.com"})
    assert r.status_code == 421


def test_azure_host_header_is_accepted(base_url):
    r = httpx2.post(f"{base_url}/mcp", json=INIT_BODY, headers={**HEADERS, "Host": AZURE_HOST})
    assert r.status_code == 200
