# AI Agent scenarios (tool traces)

Run with `python chat.py` as student `20210001`, REST calls through the Azure API Gateway
(`https://tuition-apim-ee7141.azure-api.net/api/v1`), policy search on the Azure MCP server
(`https://tuition-mcp-ee7141.azurewebsites.net/mcp`). Copied from `agent/logs/trace-<date>.jsonl`.

## 1. MCP only

- time (UTC): 2026-11-23T23:34:39
- model: `gemini-3.5-flash-lite`
- question: **When is the payment deadline?**
- tools used: `search_tuition_policies`

| # | tool | input | result |
|---|---|---|---|
| 1 | `search_tuition_policies` | `{"query": "payment deadline"}` | 3 match(es): Section 2.2, Section 2.1, Section 8.1 |

Final answer:

> The payment deadlines are:
> - **Fall 2026 term:** September 30, 2026 (Section 2.1)
> - **Spring 2027 term:** February 15, 2027 (Section 2.2)

## 2. REST API only

- time (UTC): 2026-11-23T23:34:54
- model: `gemini-3.5-flash-lite`
- question: **What is my balance?**
- tools used: `query_tuition`

| # | tool | input | result |
|---|---|---|---|
| 1 | `query_tuition` | `{}` | 20210001 overall balance 6000.00 (2026-FALL balance 3000.00, 2027-SPRING balance 3000.00) |

Final answer:

> Your total outstanding balance is **6000.00 USD**, broken down by term as follows:
> 
> - **2026-FALL:** 3000.00 USD (Deadline: September 30, 2026)
> - **2027-SPRING:** 3000.00 USD (Deadline: February 15, 2027)

## 3. Combined MCP + REST API

- time (UTC): 2026-11-23T23:35:30
- model: `gemini-3.5-flash-lite`
- question: **Can I pay my outstanding balance in installments?**
- tools used: `search_tuition_policies`, `query_tuition`

| # | tool | input | result |
|---|---|---|---|
| 1 | `search_tuition_policies` | `{"query": "installments installment plan eligibility"}` | 3 match(es): Section 3.1, Section 3.4, Section 5.1 |
| 2 | `query_tuition` | `{}` | 20210001 overall balance 6000.00 (2026-FALL balance 3000.00, 2027-SPRING balance 3000.00) |

Final answer:

> Yes, you are eligible to request an installment arrangement since your outstanding balance of **6000.00 USD** is at least $300 (Section 3.1). 
> 
> However, please note that an installment arrangement is subject to university approval; making a partial payment does not constitute an approved installment plan (Section 3.4).

## 4. Payment with explicit confirmation

- time (UTC): 2026-11-23T23:37:55
- model: `gemini-3.5-flash-lite`
- question: **Pay 500 for the fall term**
- tools used: `pay_tuition`

| # | tool | input | result |
|---|---|---|---|
| 1 | `pay_tuition` | `{"term": "2026-FALL", "amount": 500}` | SUCCESS tx AGENT-f771078e-9b8a-455a-bdcb-9564584a00da paid 500.00 remaining 2500.00 |

Final answer:

> Your payment of 500.00 USD for the 2026-FALL term has been successfully processed.
