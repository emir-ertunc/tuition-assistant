"""Calls the tool through the MCP client (in-memory, no network)."""

import pytest

from mcp import Client

import indexer
import server

pytestmark = pytest.mark.anyio


async def call(client, args):
    result = await client.call_tool("search_tuition_policies", args)
    return result


async def test_tool_is_listed_with_schema():
    async with Client(server.mcp) as client:
        tools = (await client.list_tools()).tools
    assert [t.name for t in tools] == ["search_tuition_policies"]
    tool = tools[0]
    assert "tuition policy" in tool.description
    props = tool.input_schema["properties"]
    assert tool.input_schema["required"] == ["query"]
    assert props["query"]["type"] == "string"
    assert props["top_k"]["default"] == 3
    assert props["top_k"]["minimum"] == 1
    assert props["top_k"]["maximum"] == indexer.MAX_TOP_K
    assert set(tool.output_schema["required"]) == {"document", "documentId", "query", "matches"}


@pytest.mark.parametrize(
    "query, expected",
    [
        ("When is the Fall payment deadline?", "2.1"),
        ("Can I get a refund after early withdrawal?", "6.1"),
        ("What is the late fee?", "4.1"),
        ("installment rules", "3.2"),
    ],
)
async def test_tool_returns_expected_section(query, expected):
    async with Client(server.mcp) as client:
        result = await call(client, {"query": query})
    assert not result.is_error
    data = result.structured_content
    assert data["document"] == "University_Tuition_Policies.md"
    assert data["documentId"] == "UNI-TUITION-2026-01"
    assert data["query"] == query
    assert data["matches"][0]["section"] == expected
    assert len(data["matches"]) <= 3


async def test_tool_installment_question():
    async with Client(server.mcp) as client:
        result = await call(client, {"query": "pay tuition in installments", "top_k": 5})
    sections = [m["section"] for m in result.structured_content["matches"]]
    assert len(sections) == 5
    assert {"3.1", "3.2"} & set(sections)


async def test_tool_text_content_is_json_too():
    import json

    async with Client(server.mcp) as client:
        result = await call(client, {"query": "late fee", "top_k": 1})
    assert json.loads(result.content[0].text) == result.structured_content


async def test_empty_query_gives_tool_error():
    async with Client(server.mcp) as client:
        result = await call(client, {"query": "   "})
    assert result.is_error
    assert "query must not be empty" in result.content[0].text


async def test_top_k_above_limit_gives_tool_error():
    async with Client(server.mcp) as client:
        result = await call(client, {"query": "late fee", "top_k": indexer.MAX_TOP_K + 1})
    assert result.is_error
    assert "top_k" in result.content[0].text


async def test_index_is_not_rebuilt_per_call(monkeypatch):
    index_before = server.policy_index
    built_at = index_before.built_at

    def fail(*args, **kwargs):
        raise AssertionError("index must not be rebuilt for a search")

    monkeypatch.setattr(indexer.PolicyIndex, "build", fail)
    monkeypatch.setattr(indexer.PolicyIndex, "from_file", fail)

    async with Client(server.mcp) as client:
        for q in ["deadline", "refund", "installment"]:
            assert not (await call(client, {"query": q})).is_error

    assert server.policy_index is index_before
    assert server.policy_index.built_at == built_at
