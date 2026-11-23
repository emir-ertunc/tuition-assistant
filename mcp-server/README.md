# MCP Server – Tuition Policies

This server makes the university policy document (`data/University_Tuition_Policies.md`,
document ID `UNI-TUITION-2026-01`) searchable for the AI Agent. It exposes one MCP tool,
`search_tuition_policies`, over streamable HTTP at `/mcp`.

The document is split into sections and indexed **once, when the server starts**. A tool
call only searches the ready index; nothing is re-read or re-indexed per question.

The MCP server is called directly by the agent. It does not go through the API gateway
(the gateway is only in front of the Tuition REST API).

## Files

| File | What it does |
|---|---|
| `server.py` | MCP server, tool definition, `/health` route, settings from env |
| `indexer.py` | Chunking, tokenizer and BM25 index |
| `retrieval_demo.py` | Runs sample searches through the MCP client and prints the results |
| `data/University_Tuition_Policies.md` | The policy document |
| `tests/` | pytest tests (indexer, tool via in-memory client, tool over real HTTP) |

## Run locally

```
cd mcp-server
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python server.py
```

Output:

```
INFO tuition-policies: Indexed University_Tuition_Policies.md (UNI-TUITION-2026-01): 25 sections
INFO tuition-policies: Starting MCP server on http://127.0.0.1:8001/mcp
```

- MCP endpoint: `http://127.0.0.1:8001/mcp` (streamable HTTP)
- Health check: `http://127.0.0.1:8001/health` → `{"status": "ok", "sections": 25, ...}`

Quick check with the MCP Python client:

```python
import asyncio
from mcp import Client

async def main():
    async with Client("http://127.0.0.1:8001/mcp") as client:
        result = await client.call_tool("search_tuition_policies", {"query": "late fee"})
        print(result.structured_content)

asyncio.run(main())
```

## Environment variables

Read from the environment or from a `.env` file in this folder (see `.env.example`).

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `127.0.0.1` | Bind address. Use `0.0.0.0` on Azure App Service. |
| `MCP_PORT` | `8001` | Port. If not set, `PORT` is used, then `8001`. |
| `POLICY_FILE` | `data/University_Tuition_Policies.md` | Policy document. Relative paths are resolved from this folder. |
| `MCP_ALLOWED_HOSTS` | empty | Comma separated public host names, e.g. `my-app.azurewebsites.net`. |
| `MCP_ALLOWED_ORIGINS` | empty | Comma separated origins, only for browser clients. |
| `MCP_STATELESS` | `true` | Stateless streamable HTTP (no server side session). |

### Host header check (DNS rebinding protection)

The MCP SDK checks the `Host` header. When the server binds to `127.0.0.1` and
`MCP_ALLOWED_HOSTS` is empty, only `localhost` / `127.0.0.1` are accepted (SDK default).

On Azure the requests arrive with `Host: <app>.azurewebsites.net`. Put that name in
`MCP_ALLOWED_HOSTS`, otherwise the server answers `421 Invalid Host header`. The SDK compares
exact names (no `*.azurewebsites.net` wildcard), so write the full app name. For every listed
name `name:*` (any port) is also allowed, and localhost always stays allowed.

Stateless mode is on by default because App Service can restart or scale the app and there is
no shared session store. The search tool keeps no state between calls, so nothing is lost.

### Azure App Service settings (for the deploy step)

```
MCP_HOST=0.0.0.0
MCP_PORT=8000
MCP_ALLOWED_HOSTS=<app-name>.azurewebsites.net
```

Startup command: `python server.py`. Health check path: `/health`.

## Tool: `search_tuition_policies`

Description given to the model (short version): searches the official tuition policy document
and returns matching sections with section number, heading and text. To be used for general
policy questions (deadlines, installments, late fees, scholarships, refunds, payment rules).
It does not know student balances or payments; those come from the Tuition REST API.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Policy question or keywords in English, e.g. 'late fee for overdue tuition'."
    },
    "top_k": {
      "type": "integer",
      "default": 3,
      "minimum": 1,
      "maximum": 10,
      "description": "How many sections to return (1-10)."
    }
  },
  "required": ["query"]
}
```

### Output

The tool returns structured content (it also has an output schema), and the same JSON as text.

```json
{
  "document": "University_Tuition_Policies.md",
  "documentId": "UNI-TUITION-2026-01",
  "query": "What is the late fee?",
  "matches": [
    {
      "section": "4.1",
      "heading": "Late fee rule",
      "parentHeading": "Late fees",
      "text": "A 2% one-time late fee may be assessed on an overdue amount after the applicable due date, unless an approved exception applies. This document describes the rule but does not calculate or post fees automatically.",
      "score": 7.5102
    },
    {
      "section": "4.2",
      "heading": "Example",
      "parentHeading": "Late fees",
      "text": "If $1,000 is overdue and no exception applies, the illustrative late fee is $20. Whether a fee has actually been posted must be checked in the tuition system.",
      "score": 6.7415
    }
  ]
}
```

- `section` is the section number in the document (`"3.2"`, or `"1"` / `"9"` for sections
  without subsections), so the answer can cite it.
- `parentHeading` is the main section title. It helps with short headings such as "Example".
- `matches` is sorted by score (highest first). Only sections with a score above 0 are returned,
  so a query with no known words gives `"matches": []`.

### Errors

Errors come back as a tool result with `isError: true` and a message:

| Input | Message |
|---|---|
| empty or blank `query` | `query must not be empty. Ask a question about tuition policies, e.g. 'late fee'.` |
| `top_k` outside 1–10 | validation error for `top_k` |

## Indexing approach

### Chunking

The document already has a clear structure: `## N. Title` for main sections and `### N.M Title`
for subsections. Each subsection is one chunk. A main section without subsections
(1. Scope and terminology, 9. Guidance for AI/MCP implementation) is one chunk. The title and
metadata lines before section 1 are not indexed. This gives **25 chunks**:

```
1 | 2.1 2.2 2.3 | 3.1 3.2 3.3 3.4 | 4.1 4.2 4.3 | 5.1 5.2 | 6.1 6.2 6.3 | 7.1 7.2 7.3 7.4 | 8.1 8.2 8.3 8.4 | 9
```

Splitting by subsection keeps every chunk about a single rule and short (one or two
paragraphs), and the section number comes directly from the heading, so results can be
cited exactly. Fixed-size chunks would cut rules in half and lose the section number.

### Tokenizing

- lower case, split on anything that is not a letter or digit (`$1,000` → `1`, `000`;
  `2026-FALL` → `2026`, `fall`)
- remove a small list of English stopwords (`the`, `is`, `what`, `can`, `my`, ...)
- also remove words that describe the whole document rather than one section (`rule`,
  `policy`, `regulation`, `guideline` and their plurals). Without this, the query
  "installment rules" ranked 4.1 *Late fee rule* first, only because "rule" is rare in the
  document and appears in that heading. Now it returns 3.2, 3.3, 3.4.
- light plural handling: `installments` → `installment`, `policies` → `policy`

The indexed text of a chunk is its main section title + its heading (counted twice, so a
matching heading weighs a bit more) + its body.

### Why BM25 (full-text)

- The document is small (about 7 KB) and uses fixed terms that users also use: *deadline*,
  *installment*, *late fee*, *refund*, *scholarship*. Keyword matching works well for this.
- BM25 rewards rare terms (IDF): "refund" only appears in section 6, so it pulls those
  sections up, while common words like "tuition" or "payment" count less.
- Length normalization stops long sections from winning only because they have more words.
- It is deterministic and easy to test: the same query always gives the same sections, so the
  tests can check exact section numbers.
- No embedding model, API key or vector database is needed. The index is built in a few
  milliseconds at startup and lives in memory.

BM25 is implemented in `indexer.py` in plain Python (Okapi BM25, `k1 = 1.5`, `b = 0.75`,
IDF = `ln((N - df + 0.5) / (df + 0.5) + 1)`). The downside is that synonyms are not matched
(for example "penalty" does not match "late fee" by itself); for this document the words
users ask with are mostly the same words the policy uses, and the agent can rephrase the
query if the first search finds nothing.

### Built once

`server.py` builds the index at module load (`policy_index = PolicyIndex.from_file(...)`),
before the server starts listening. The startup log shows `Indexed ... 25 sections` once, and
`/health` shows the `indexedAt` time. `tests/test_server.py::test_index_is_not_rebuilt_per_call`
makes rebuilding fail and checks that several searches still work with the same index object.

## Tests

```
cd mcp-server
.venv\Scripts\activate
pytest -v
```

| Test file | What is tested |
|---|---|
| `tests/test_indexer.py` | 25 chunks with the right section IDs, headings and text; tokenizer; searches (deadline → 2.1, installments → 3.x, "installment rules" → 3.2, refund → 6.1, late fee → 4.1, scholarship → 5.1); result format; empty query; `top_k` limits |
| `tests/test_server.py` | Tool called through the MCP client (in-memory): tool list and schema, expected sections, errors, index not rebuilt per call |
| `tests/test_http.py` | Server started with uvicorn on a free port and called over real streamable HTTP; `/health`; unknown `Host` header → 421, configured Azure host → 200 |

### Retrieval demo (evidence)

```
python server.py                       # terminal 1
python retrieval_demo.py --out ../docs/mcp-retrieval-tests.txt   # terminal 2
```

`retrieval_demo.py` connects with the MCP client, runs four different policy questions
(payment deadline, installments, refund, late fee) and an empty query, and prints the
returned sections with scores. The saved output is in
[`docs/mcp-retrieval-tests.txt`](../docs/mcp-retrieval-tests.txt).
Use `--url https://<app>.azurewebsites.net/mcp` to run it against the deployed server, or
`--in-memory` to run it without starting the server.
