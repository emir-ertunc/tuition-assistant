"""Runs a few policy searches through the MCP tool and prints the results.

Usage:
  python retrieval_demo.py                                   # server must be running (python server.py)
  python retrieval_demo.py --url https://<app>.azurewebsites.net/mcp
  python retrieval_demo.py --in-memory                       # no running server needed
  python retrieval_demo.py --out ../docs/mcp-retrieval-tests.txt
"""

import argparse
import asyncio
import io
import sys
import textwrap
from contextlib import redirect_stdout
from datetime import datetime, timezone

from mcp import Client

TOOL = "search_tuition_policies"

# (test name, query, section we expect at the top)
QUERIES = [
    ("Payment deadline", "What is the payment deadline for the Fall term?", "2.1"),
    ("Installments", "How many installments can I split my tuition balance into?", "3.x"),
    ("Refund", "Do I get a refund if I withdraw early in the term?", "6.1"),
    ("Late fee", "What is the late fee if I pay after the deadline?", "4.1"),
]


def expected_ok(expected: str, sections: list[str]) -> bool:
    if expected.endswith(".x"):
        return any(s.startswith(expected[:-1]) for s in sections)
    return bool(sections) and sections[0] == expected


async def run(target, label: str) -> bool:
    all_ok = True
    print("MCP retrieval tests - tuition policy search")
    print(f"Date (UTC): {datetime.now(timezone.utc):%Y-%m-%d %H:%M}")
    print(f"Server: {label}")
    print(f"Tool: {TOOL}")
    print("=" * 78)

    async with Client(target) as client:
        tools = (await client.list_tools()).tools
        print("Tools on server:", ", ".join(t.name for t in tools))
        print()

        for i, (name, query, expected) in enumerate(QUERIES, start=1):
            result = await client.call_tool(TOOL, {"query": query, "top_k": 3})
            data = result.structured_content
            sections = [m["section"] for m in data["matches"]]
            ok = not result.is_error and expected_ok(expected, sections)
            all_ok &= ok

            print(f"Test {i}: {name}")
            print(f"  query:    {query!r}")
            print(f"  document: {data['document']} ({data['documentId']})")
            print(f"  expected: section {expected}  ->  {'PASS' if ok else 'FAIL'}")
            for rank, m in enumerate(data["matches"], start=1):
                print(f"  #{rank} section {m['section']} - {m['heading']} "
                      f"({m['parentHeading']}), score {m['score']:.4f}")
                body = textwrap.fill(m["text"], width=70, initial_indent="       ",
                                     subsequent_indent="       ")
                print(body)
            print("-" * 78)

        # input check
        result = await client.call_tool(TOOL, {"query": "   "})
        ok = result.is_error
        all_ok &= ok
        print("Extra: empty query")
        print(f"  is_error: {result.is_error}  ->  {'PASS' if ok else 'FAIL'}")
        print(f"  message:  {result.content[0].text}")
        print("=" * 78)

    print(f"Result: {'ALL PASSED' if all_ok else 'SOME TESTS FAILED'}")
    return all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Run sample searches against the MCP server.")
    parser.add_argument("--url", default="http://127.0.0.1:8001/mcp", help="MCP endpoint URL")
    parser.add_argument("--in-memory", action="store_true", help="load server.py in this process")
    parser.add_argument("--out", help="also write the output to this file")
    args = parser.parse_args()

    if args.in_memory:
        import server
        target, label = server.mcp, "in-memory (server.py loaded in this process)"
    else:
        target, label = args.url, f"{args.url} (streamable HTTP)"

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        ok = asyncio.run(run(target, label))
    output = buffer.getvalue()
    sys.stdout.write(output)

    if args.out:
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write(output)
        print(f"\nSaved to {args.out}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
