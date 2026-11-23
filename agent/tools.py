"""Tool definitions given to the LLM and the code that runs them.

The student number is NOT a tool parameter. ToolRunner gets it once after login (from
/auth/me) and uses it for every api call, so a number written in the chat can never select
another student's data.

Every tool returns a dict that is sent back to the LLM as the function response:
    {"ok": true, "data": {...}}  or  {"ok": false, "error": {"status", "code", "message", ...}}
"""

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Callable

from api_client import ApiError, TuitionApiClient
from mcp_client import PolicySearchClient, PolicySearchError

TERM_PATTERN = r"^\d{4}-(FALL|SPRING|SUMMER)$"

TOOL_SPECS = [
    {
        "name": "search_tuition_policies",
        "description": (
            "Search the University Tuition Policies document. Use it for rules: payment deadlines, "
            "installments, late fees, scholarships, refunds, payment and confirmation rules. "
            "Returns matching policy sections with their section numbers."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for, e.g. 'installment eligibility'."},
                "top_k": {"type": "integer", "description": "How many sections to return (default 3)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_tuition",
        "description": (
            "Get the live tuition data of the logged-in student from the Tuition API: tuition total, "
            "paid amount, balance, currency and payment deadline for each term and overall. "
            "Always works on the logged-in student's own account."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {
                    "type": "string",
                    "description": "Optional term like '2026-FALL' or '2027-SPRING'. Leave empty for all terms.",
                },
            },
        },
    },
    {
        "name": "pay_tuition",
        "description": (
            "Submit a tuition payment for the logged-in student. Only call it when the student clearly "
            "asks to make a payment now and the term and amount are known. The application shows the "
            "payment details and asks the student to confirm before anything is sent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "term": {"type": "string", "description": "Term to pay, e.g. '2026-FALL'."},
                "amount": {"type": "number", "description": "Amount to pay, positive, at most 2 decimals."},
            },
            "required": ["term", "amount"],
        },
    },
]


@dataclass
class PaymentPreview:
    student_no: str
    full_name: str
    term: str
    amount: str
    balance: str
    currency: str
    payment_deadline: str


ConfirmFn = Callable[[PaymentPreview], bool]


@dataclass
class ToolOutcome:
    name: str
    args: dict
    result: dict
    summary: str
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.result.get("ok"))


def ok(data) -> dict:
    return {"ok": True, "data": data}


def fail(code: str, message: str, status: int | None = None, details=None) -> dict:
    return {"ok": False, "error": {"status": status, "code": code, "message": message, "details": details}}


class ToolRunner:
    def __init__(self, api: TuitionApiClient, policies: PolicySearchClient, student_no: str,
                 confirm: ConfirmFn):
        self.api = api
        self.policies = policies
        self.student_no = student_no
        self.confirm = confirm
        self._handlers = {
            "search_tuition_policies": self._search_policies,
            "query_tuition": self._query_tuition,
            "pay_tuition": self._pay_tuition,
        }

    def run(self, name: str, args: dict | None) -> ToolOutcome:
        args = dict(args or {})
        handler = self._handlers.get(name)
        if handler is None:
            result = fail("UNKNOWN_TOOL", f"there is no tool called {name}")
        else:
            try:
                result = handler(args)
            except ApiError as exc:
                result = {"ok": False, "error": exc.to_dict()}
            except PolicySearchError as exc:
                result = fail("MCP_ERROR", str(exc))
            except Exception as exc:  # keep the chat running, the model gets the error instead
                result = fail("TOOL_ERROR", f"{type(exc).__name__}: {exc}")
        return ToolOutcome(name=name, args=args, result=result, summary=summarize(name, result))

    # ---------- tools ----------

    def _search_policies(self, args: dict) -> dict:
        query = str(args.get("query", "")).strip()
        if not query:
            return fail("INVALID_INPUT", "query is required")
        top_k = args.get("top_k") or 3
        try:
            top_k = max(1, min(int(top_k), 5))
        except (TypeError, ValueError):
            top_k = 3
        return ok(self.policies.search(query, top_k))

    def _query_tuition(self, args: dict) -> dict:
        # only "term" is read; anything else the model sends (like a student number) is ignored
        term = _clean_term(args.get("term"))
        return ok(self.api.query_tuition(self.student_no, term))

    def _pay_tuition(self, args: dict) -> dict:
        term = _clean_term(args.get("term"))
        if not term:
            return fail("INVALID_INPUT", "term is required for a payment")
        amount = _parse_amount(args.get("amount"))
        if amount is None:
            return fail("INVALID_INPUT", "amount must be a positive number with at most 2 decimals")

        # current balance straight from the api, not from what the model remembers
        current = self.api.query_tuition(self.student_no, term)
        term_row = next((t for t in current.get("terms", []) if t.get("term") == term), None)
        if term_row is None:
            return fail("NOT_FOUND", f"no tuition found for term {term}", 404)
        balance = Decimal(str(term_row["balance"]))
        if balance <= 0:
            return fail("NOTHING_TO_PAY", f"the balance for {term} is already 0.00, no payment was made")
        if amount > balance:
            return fail(
                "AMOUNT_EXCEEDS_BALANCE",
                f"amount {amount} is more than the remaining balance {balance:.2f}, no payment was made",
            )

        preview = PaymentPreview(
            student_no=self.student_no,
            full_name=current.get("fullName", ""),
            term=term,
            amount=f"{amount:.2f}",
            balance=f"{balance:.2f}",
            currency=term_row.get("currency", ""),
            payment_deadline=str(term_row.get("paymentDeadline", "")),
        )
        if not self.confirm(preview):
            return {
                "ok": False,
                "error": {
                    "status": None,
                    "code": "NOT_CONFIRMED",
                    "message": "The student did not confirm the payment. No payment was sent to the API.",
                    "details": None,
                },
            }

        transaction_id = f"AGENT-{uuid.uuid4()}"
        return ok(self.api.pay_tuition(self.student_no, term, preview.amount, transaction_id))


def _clean_term(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def _parse_amount(value) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        amount = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        return None
    if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
        return None
    return amount.quantize(Decimal("0.01"))


# ---------- short summaries for the tool trace ----------

def summarize(name: str, result: dict) -> str:
    if not result.get("ok"):
        err = result.get("error", {})
        status = f"{err.get('status')} " if err.get("status") else ""
        return f"error {status}{err.get('code')}: {err.get('message')}"
    data = result.get("data", {})
    if name == "search_tuition_policies":
        sections = [f"{m.get('section')}" for m in data.get("matches", [])]
        return f"{len(sections)} match(es): " + ", ".join(f"Section {s}" for s in sections)
    if name == "query_tuition":
        terms = ", ".join(f"{t['term']} balance {t['balance']}" for t in data.get("terms", []))
        return f"{data.get('studentNo')} overall balance {data.get('balance')} ({terms})"
    if name == "pay_tuition":
        return (f"{data.get('status')} tx {data.get('transactionId')} paid {data.get('paidAmount')} "
                f"remaining {data.get('remainingBalance')}")
    return "ok"
