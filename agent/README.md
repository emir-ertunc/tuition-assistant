# AI Agent

Command line chat for students. The agent sends the question to the LLM (Gemini Flash)
together with three tool definitions. The LLM only decides which tool to call; the agent runs
the tool (MCP policy search or the Tuition API through the API Gateway), sends the result back
to the LLM, and the LLM writes the final answer from that result. The LLM never calls a backend
by itself.

```
student ──> chat.py ──> agent.py ──question + tool specs──> Gemini
                           │  <──── function call(s) ──────────┘
                           │
                           ├── search_tuition_policies ──> MCP server  (MCP_SERVER_URL, streamable HTTP)
                           ├── query_tuition ────────────> API Gateway ──> Tuition API  GET  /banking/tuitions/{studentNo}
                           └── pay_tuition ──[confirm]───> API Gateway ──> Tuition API  POST /banking/payments
                           │
                           └── tool results ──> Gemini ──> final answer + tool trace
```

## Files

| File | What it does |
|---|---|
| `chat.py` | CLI: login (username + `getpass` password), question loop, payment confirmation prompt |
| `agent.py` | tool calling loop (max N rounds), system prompt, tool trace + JSON lines log |
| `llm.py` | `ChatModel` interface and the `GeminiChat` implementation (`google-genai`, automatic function calling off) |
| `tools.py` | tool definitions for the LLM and `ToolRunner` that executes them |
| `api_client.py` | httpx client for `/auth/token`, `/auth/me`, query and pay |
| `mcp_client.py` | MCP client (`mcp` 2.x `Client`) for `search_tuition_policies` |
| `config.py` | settings from `.env` |
| `tests/` | pytest tests with a fake LLM, fake API and fake MCP |

## Run

The Tuition API (or the gateway in front of it) and the MCP server must be running.

```
cd agent
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env      (then fill the values)
python chat.py
```

Log in with a student account (for example `20210001` / `student123`, see
`tuition-api/README.md`) and ask questions. Type `exit` to quit.

### Environment variables

| Name | Example | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | – | key from Google AI Studio |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Flash model. The demo uses `gemini-3.5-flash-lite`: on the free tier `gemini-3.6-flash` allowed only 20 requests per day and one question takes 2-3 requests (question, tool call, answer). Every model has its own daily quota. `gemini-3.8-flash` often answered 503 "high demand" in our tests. |
| `GATEWAY_BASE_URL` | `https://<apim-name>.azure-api.net/api/v1` | every REST call goes here. For a local test without the gateway: `http://localhost:8000/api/v1` |
| `GATEWAY_SUBSCRIPTION_KEY` | – | sent as `Ocp-Apim-Subscription-Key` when not empty |
| `MCP_SERVER_URL` | `http://localhost:8001/mcp` | policy MCP server, not behind the gateway |
| `AGENT_MAX_TOOL_ROUNDS` | `5` | optional, max tool rounds per question |
| `AGENT_LOG_DIR` | `logs` | optional, where the trace files are written |

## Tools

| Tool | Parameters | Backend |
|---|---|---|
| `search_tuition_policies` | `query`, `top_k?` | MCP server tool `search_tuition_policies` |
| `query_tuition` | `term?` | `GET {GATEWAY_BASE_URL}/banking/tuitions/{studentNo}?term=` with the student's bearer token |
| `pay_tuition` | `term`, `amount` | `POST {GATEWAY_BASE_URL}/banking/payments` body `{studentNo, term, amount, transactionId}` |

**The student number is not a tool parameter.** After login the agent calls `/auth/me` and
uses that `studentNo` for every call. If the question contains another student's number
("what is the balance of 20210002?") the model cannot pass it anywhere; extra arguments are
ignored and the API would answer 403 anyway because the token belongs to the logged-in student.

Every tool result goes back to the LLM in one shape:

```json
{"ok": true,  "data": { ...api or mcp response... }}
{"ok": false, "error": {"status": 422, "code": "AMOUNT_EXCEEDS_BALANCE", "message": "...", "details": null}}
```

API errors keep the API's own `code` and `message` (401, 403, 404, 409, 422 ...), so the model
can explain what went wrong instead of making something up.

## Flow of one question

1. `send_message(question)` → Gemini answers with text or with function calls.
2. For each function call the agent runs the tool (`ToolRunner.run`) and prints it in the trace.
3. All results of that round are sent back with `send_tool_results`.
4. Steps 2–3 repeat until the model answers with text. After `AGENT_MAX_TOOL_ROUNDS` rounds the
   pending calls get a `TOOL_LIMIT` result and the next request is sent with function calling
   mode `NONE`, so the model has to answer with what it already has.
5. The answer and the trace are printed and appended to `logs/trace-<date>.jsonl`.

The system prompt tells the model to use MCP for policy questions, the API for the student's
live numbers and both for combined questions; to give section numbers ("Section 3.2"); never to
promise installment approval (Section 3.4); and never to say a payment succeeded before the API
returns `SUCCESS` (Section 7.4).

## Payment confirmation

The confirmation is in the code, not only in the prompt (policy Section 7.3: "Can I pay $500?"
is not an authorization). When the model calls `pay_tuition`:

1. amount is checked (positive, max 2 decimals),
2. the current balance of that term is read from the API again,
3. an amount larger than the balance or a term with 0 balance is stopped here,
4. the student, term, amount, current balance and deadline are shown and the user must type `yes`,
5. only then the payment is sent with a new `transactionId` (`AGENT-<uuid4>`, idempotency key).

Anything other than `yes` returns `NOT_CONFIRMED` to the model and the API is not called.

```
  +-------------------- Payment confirmation --------------------
  | Student          : 20210001 Ayse Yilmaz
  | Term             : 2026-FALL
  | Amount to pay    : 500.00 USD
  | Current balance  : 3000.00 USD
  | Payment deadline : 2026-09-30
  +--------------------------------------------------------------
  Type "yes" to send this payment, anything else cancels:
```

## Tool trace

Every question prints the tools the model picked, their inputs and a short result, then the
answer. Example from a live run (`gemini-3.6-flash`, local API and MCP server):

```
> When is the payment deadline?
Tool trace:
  [tool] search_tuition_policies({"query": "payment deadline"})
     -> 3 match(es): Section 2.2, Section 2.1, Section 8.1

Assistant: The payment deadlines are as follows:
* Fall 2026 Term: September 30, 2026 (Section 2.1)
* Spring 2027 Term: February 15, 2027 (Section 2.2)

> What is my balance?
Tool trace:
  [tool] query_tuition({})
     -> 20210001 overall balance 5500.00 (2026-FALL balance 2500.00, 2027-SPRING balance 3000.00)

Assistant: Your total outstanding balance is $5,500.00 USD. (2026-FALL: $2,500.00, 2027-SPRING: $3,000.00)

> Can I pay my outstanding balance in installments?
Tool trace:
  [tool] query_tuition({})
     -> 20210001 overall balance 5500.00 (2026-FALL balance 2500.00, 2027-SPRING balance 3000.00)
  [tool] search_tuition_policies({"query": "installment payment eligibility guidelines approval"})
     -> 3 match(es): Section 3.1, Section 3.4, Section 8.2

Assistant: Your total outstanding balance is $5,500.00 USD ... Students with an outstanding balance
of at least $300 may request an installment arrangement (Section 3.1) ... Up to three installments
(Section 8.2), about $1,833.33 USD each ... Any installment plan is subject to university approval;
partial payments alone are not an approved plan (Section 3.4).

> Can I pay $500?
Tool trace:
  [tool] search_tuition_policies({"query": "partial payment payment rules"})
  [tool] search_tuition_policies({"query": "Section 7 payment requests confirmation"})

Assistant: ... An inquiry like "Can I pay $500?" is not a payment authorization (Section 7.3).
Would you like to proceed with making a $500.00 USD payment for 2026-FALL?

> Please pay 500 USD for the 2026-FALL term now.
Tool trace:
  [tool] pay_tuition({"term": "2026-FALL", "amount": 500})
  (confirmation box, user typed "yes")
     -> SUCCESS tx AGENT-5aa4cdc4-6b44-4c5f-a7bc-be6074d3c344 paid 500.00 remaining 2500.00

Assistant: Your payment of $500.00 USD for the 2026-FALL term has been successfully processed.
Remaining Balance (2026-FALL): $2,500.00 USD. Transaction ID: AGENT-5aa4cdc4-...

> What is the tuition balance of student 20210002?
Tool trace:
  (no tool used)

Assistant: I can only access and display information for your own account (Ayse Yilmaz,
Student No. 20210001).
```

The same information is written to `logs/trace-YYYY-MM-DD.jsonl`, one line per question:

```json
{"time": "...", "studentNo": "20210001", "model": "gemini-3.6-flash",
 "question": "What is my balance?", "toolsUsed": ["query_tuition"],
 "steps": [{"round": 1, "tool": "query_tuition", "args": {}, "ok": true,
            "summary": "20210001 overall balance 6000.00 (...)", "result": {"ok": true, "data": {...}}}],
 "rounds": 1, "stoppedByLimit": false, "error": null, "answer": "..."}
```

## Tests

```
cd agent
.venv\Scripts\activate
pytest
```

No API key, database, API or MCP server is needed. The real agent loop and `ToolRunner` run
with a scripted fake LLM (`tests/conftest.py`), a fake API and a fake policy search.

| File | Covers |
|---|---|
| `test_agent.py` | MCP-only flow, API-only flow, combined flow (same round and two rounds), no tool for small talk, payment declined → no API call, payment confirmed → API call with new transactionId, amount over balance / invalid amount, other student number in the prompt or in the arguments is not used, max round limit, API and MCP errors passed to the LLM, unknown tool, LLM failure, JSON lines trace |
| `test_clients.py` | httpx requests (form login, bearer token, subscription header, URL, pay body), API / gateway error parsing, unreachable gateway, `GeminiChat` with a fake sdk client (automatic function calling off, function responses in history, mode `NONE`, history rollback after a failed request) |
| `test_mcp_client.py` | MCP client against an in-process MCP server: results, tool error, unreachable server |

## LLM cost

- Gemini Flash models have a **free tier** on the Gemini Developer API (Google AI Studio key),
  which is enough for development and the demo. The free tier of `gemini-3.6-flash` allows about
  5 requests per minute; on a 429 the client waits the time Gemini asks for ("retry in 44s", max
  60 s) and tries again. Paid price of `gemini-3.6-flash` / `gemini-3.8-flash` is about
  $0.75 / 1M input and $3.75 / 1M output tokens (until 2026-12-31); `gemini-3.5-flash-lite` is
  cheaper ($0.30 / $2.50).
- One question is usually 2 requests (tool call + answer), 3 for combined questions. With the
  short system prompt and 3 small tool definitions a request is a few thousand tokens, so even
  on the paid tier a question costs a fraction of a cent.
- Only short policy excerpts (top 3 sections) are sent to the model, not the whole document.
- `AGENT_MAX_TOOL_ROUNDS` limits how many requests one question can make.
- All tests use a fake LLM, so running the test suite costs nothing and does not depend on
  rate limits.
