"""Writes docs/agent-scenarios.md from the agent trace log (the evidence for the README).

Takes the last successful run of each demo question and the last confirmed payment.

usage (in the agent folder):
    python export_traces.py logs/trace-2026-11-23.jsonl ../docs/agent-scenarios.md
"""

import json, sys
log_file = sys.argv[1]
out_file = sys.argv[2] if len(sys.argv) > 2 else "../docs/agent-scenarios.md"
rows = [json.loads(l) for l in open(log_file, encoding="utf-8") if l.strip()]
ok = [r for r in rows if not r.get("error") and r.get("steps")]
wanted = [
    ("1. MCP only", "When is the payment deadline?"),
    ("2. REST API only", "What is my balance?"),
    ("3. Combined MCP + REST API", "Can I pay my outstanding balance in installments?"),
]
pay = [r for r in ok if r.get("model", "").endswith("flash-lite") and any(s.get("tool") == "pay_tuition" and s.get("ok") for s in r["steps"])]
out = ["# AI Agent scenarios (tool traces)", "",
       "Run with `python chat.py` as student `20210001`, REST calls through the Azure API Gateway",
       "(`https://tuition-apim-ee7141.azure-api.net/api/v1`), policy search on the Azure MCP server",
       "(`https://tuition-mcp-ee7141.azurewebsites.net/mcp`). Copied from `agent/logs/trace-<date>.jsonl`.", ""]
def section(title, r):
    out.extend([f"## {title}", "", f"- time (UTC): {r['time'][:19]}", f"- model: `{r['model']}`",
                f"- question: **{r['question']}**", f"- tools used: {', '.join('`'+t+'`' for t in r['toolsUsed'])}", "",
                "| # | tool | input | result |", "|---|---|---|---|"])
    for i, s in enumerate(r["steps"], 1):
        out.append(f"| {i} | `{s['tool']}` | `{json.dumps(s['args'])}` | {s.get('summary','')} |")
    out.extend(["", "Final answer:", "", "> " + r["answer"].replace("\n", "\n> "), ""])
for title, q in wanted:
    hits = [r for r in ok if r["question"].strip() == q and r.get("model", "").endswith("flash-lite")]
    if hits: section(title, hits[-1])
if pay: section("4. Payment with explicit confirmation", pay[-1])
open(out_file, "w", encoding="utf-8", newline="\n").write("\n".join(out))
print("written:", [t for t, q in wanted], "payment:", bool(pay))
