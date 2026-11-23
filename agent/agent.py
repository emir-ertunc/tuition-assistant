"""Tool calling loop.

    question -> LLM -> tool calls? -> run tools -> results back to LLM -> ... -> final answer

The LLM only chooses tools and writes the answer. The tools (MCP search, Tuition API) are
always run here by ToolRunner. The loop stops after max_rounds tool rounds; then the model
has to answer with what it already has.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from llm import ChatModel, LlmError, ToolResult
from tools import ToolRunner

SYSTEM_PROMPT = """You are the University Tuition Assistant. You help one logged-in student with tuition questions.

Logged-in student: {student_no} ({full_name}). Today is {today}.

Tools:
- search_tuition_policies: the University Tuition Policies document (deadlines, installments, late fees,
  scholarships, refunds, payment and confirmation rules). Use it for every policy question. Do not answer
  policy questions from memory. Write the search query in English, even if the question is in another
  language.
- query_tuition: live tuition data of the logged-in student (tuition total, paid amount, balance, currency,
  payment deadline per term). Use it for every question about the student's own numbers. Never guess amounts,
  and call it again for each new question instead of reusing numbers from earlier messages (balances change
  after payments).
- pay_tuition: submits a payment for the logged-in student.

How to pick tools:
- Only a general policy question (for example "When is the payment deadline?", "What is the late fee?")
  -> search_tuition_policies only. Do not query the student's account for these.
- Only about the student's own balance or payments -> query_tuition.
- A question that needs both the rules and the student's numbers (for example "Can I pay my outstanding
  balance in installments?") -> call both tools and combine the results.

Rules:
1. When you use policy text, give its section number, for example "(Section 3.2)". Only cite sections that
   appear in the search results.
2. Installments: you can explain eligibility and how the balance could be split, but an installment plan
   needs university approval. Never say that a plan is approved or will be approved (Section 3.4). A partial
   payment is not an approved installment plan.
3. Payments: call pay_tuition only when the student clearly asks to pay now and the term and amount are
   known. A question like "Can I pay $500?" is not a payment request (Section 7.3); answer it and ask whether
   they want to make the payment. The application itself shows the details and asks the student to confirm,
   so do not ask for confirmation again after calling the tool.
4. Never say a payment was made unless pay_tuition returned ok=true with status SUCCESS. If the result is
   NOT_CONFIRMED or an error, say clearly that no payment was made.
5. You can only see the logged-in student's account. The tools always use the logged-in student number. If
   the student asks about another student number, say that you can only show their own account.
6. If a tool returns an error, explain it shortly with its code and message. Do not make up data.
7. Keep answers short and clear. Show money with its currency. Answer in the language of the question."""

LIMIT_MESSAGE = (
    "Tool call limit reached for this question. Do not call more tools; answer with the information you have."
)


def build_system_prompt(student_no: str, full_name: str, today: date | None = None) -> str:
    return SYSTEM_PROMPT.format(
        student_no=student_no, full_name=full_name or "unknown name", today=(today or date.today()).isoformat()
    )


@dataclass
class TraceStep:
    round: int
    tool: str
    args: dict
    ok: bool
    summary: str
    result: dict


@dataclass
class AgentAnswer:
    question: str
    answer: str
    steps: list[TraceStep] = field(default_factory=list)
    rounds: int = 0
    stopped_by_limit: bool = False
    error: str | None = None

    @property
    def tools_used(self) -> list[str]:
        return [step.tool for step in self.steps]


class TraceLog:
    """Appends one JSON line per question to logs/trace-YYYY-MM-DD.jsonl."""

    def __init__(self, log_dir: Path, student_no: str, model: str = ""):
        self.log_dir = Path(log_dir)
        self.student_no = student_no
        self.model = model

    def write(self, item: AgentAnswer) -> Path:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now()
        path = self.log_dir / f"trace-{now:%Y-%m-%d}.jsonl"
        record = {
            "time": now.isoformat(timespec="seconds"),
            "studentNo": self.student_no,
            "model": self.model,
            "question": item.question,
            "toolsUsed": item.tools_used,
            "steps": [asdict(step) for step in item.steps],
            "rounds": item.rounds,
            "stoppedByLimit": item.stopped_by_limit,
            "error": item.error,
            "answer": item.answer,
        }
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return path


class TuitionAgent:
    def __init__(self, llm: ChatModel, runner: ToolRunner, max_rounds: int = 5,
                 trace_log: TraceLog | None = None, echo: Callable[[str], None] | None = None):
        self.llm = llm
        self.runner = runner
        self.max_rounds = max_rounds
        self.trace_log = trace_log
        self.echo = echo or (lambda _line: None)

    def ask(self, question: str) -> AgentAnswer:
        item = AgentAnswer(question=question, answer="")
        try:
            self._run(item)
        except LlmError as exc:
            item.error = str(exc)
            item.answer = f"Sorry, the language model is not available right now ({exc})."
        if self.trace_log:
            self.trace_log.write(item)
        return item

    def _run(self, item: AgentAnswer):
        reply = self.llm.send_message(item.question)
        while reply.tool_calls:
            if item.rounds >= self.max_rounds:
                item.stopped_by_limit = True
                self.echo(f"  [limit] {self.max_rounds} tool rounds reached, asking for a final answer")
                results = [
                    ToolResult(call, {"ok": False, "error": {"code": "TOOL_LIMIT", "message": LIMIT_MESSAGE}})
                    for call in reply.tool_calls
                ]
                reply = self.llm.send_tool_results(results, allow_tools=False)
                break

            item.rounds += 1
            results = []
            for call in reply.tool_calls:
                self.echo(f"  [tool] {call.name}({json.dumps(call.args, ensure_ascii=False, default=str)})")
                outcome = self.runner.run(call.name, call.args)
                self.echo(f"     -> {outcome.summary}")
                item.steps.append(TraceStep(
                    round=item.rounds, tool=outcome.name, args=outcome.args, ok=outcome.ok,
                    summary=outcome.summary, result=outcome.result,
                ))
                results.append(ToolResult(call, outcome.result))
            reply = self.llm.send_tool_results(results)

        item.answer = reply.text or (
            "I could not finish this request. Please ask again in a simpler way."
            if item.stopped_by_limit else "I have no answer for this question."
        )
