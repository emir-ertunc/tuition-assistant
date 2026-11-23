"""Fakes for the LLM, the Tuition API and the MCP server.

The tests run the real agent loop and the real ToolRunner; only the outside systems are
replaced, so no network, API key, database or MCP server is needed.
"""

import copy

import pytest

from agent import TuitionAgent
from api_client import ApiError
from llm import ModelReply, ToolCall
from tools import ToolRunner

STUDENT_NO = "20210001"

TUITION_DATA = {
    "studentNo": STUDENT_NO,
    "fullName": "Ali Yilmaz",
    "terms": [
        {"term": "2026-FALL", "tuitionTotal": "3000.00", "paidAmount": "500.00", "balance": "2500.00",
         "currency": "USD", "paymentDeadline": "2026-09-30"},
        {"term": "2027-SPRING", "tuitionTotal": "3000.00", "paidAmount": "0.00", "balance": "3000.00",
         "currency": "USD", "paymentDeadline": "2027-02-15"},
    ],
    "tuitionTotal": "6000.00",
    "paidAmount": "500.00",
    "balance": "5500.00",
}

POLICY_RESULT = {
    "document": "University Tuition Policies",
    "documentId": "UNI-TUITION-2026-01",
    "query": "",
    "matches": [
        {"section": "3.1", "heading": "Eligibility", "text": "at least $300 ...", "score": 0.8},
        {"section": "3.4", "heading": "Partial payments versus installment approval", "text": "...", "score": 0.6},
    ],
}


class FakeLLM:
    """Returns scripted replies and remembers everything the agent sent to it."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.messages = []
        self.tool_results = []  # one list per send_tool_results call
        self.allow_tools_flags = []

    def _next(self):
        if not self.replies:
            raise AssertionError("FakeLLM ran out of scripted replies")
        reply = self.replies.pop(0)
        return reply() if callable(reply) else reply

    def send_message(self, text):
        self.messages.append(text)
        return self._next()

    def send_tool_results(self, results, allow_tools=True):
        self.tool_results.append([(r.call.name, r.response) for r in results])
        self.allow_tools_flags.append(allow_tools)
        return self._next()


class FakeApi:
    def __init__(self):
        self.data = copy.deepcopy(TUITION_DATA)
        self.query_calls = []
        self.pay_calls = []
        self.query_error = None
        self.pay_error = None

    def query_tuition(self, student_no, term=None):
        self.query_calls.append((student_no, term))
        if self.query_error:
            raise self.query_error
        if student_no != STUDENT_NO:  # same rule as the real api for a STUDENT token
            raise ApiError(403, "FORBIDDEN", "students can only access their own tuition")
        data = copy.deepcopy(self.data)
        if term:
            data["terms"] = [t for t in data["terms"] if t["term"] == term]
            if not data["terms"]:
                raise ApiError(404, "NOT_FOUND", f"no tuition for term {term}")
        return data

    def pay_tuition(self, student_no, term, amount, transaction_id):
        self.pay_calls.append({"studentNo": student_no, "term": term, "amount": amount,
                               "transactionId": transaction_id})
        if self.pay_error:
            raise self.pay_error
        return {"status": "SUCCESS", "transactionId": transaction_id, "studentNo": student_no, "term": term,
                "paidAmount": amount, "totalPaid": "1500.00", "remainingBalance": "1500.00"}


class FakePolicies:
    def __init__(self):
        self.queries = []

    def search(self, query, top_k=None):
        self.queries.append(query)
        return dict(POLICY_RESULT, query=query)


class Confirmer:
    def __init__(self, answer: bool):
        self.answer = answer
        self.previews = []

    def __call__(self, preview):
        self.previews.append(preview)
        return self.answer


def call(name, **args):
    return ModelReply(tool_calls=[ToolCall(name=name, args=args, call_id=f"id-{name}")])


def calls(*items):
    return ModelReply(tool_calls=[ToolCall(name=n, args=a) for n, a in items])


def text(answer):
    return ModelReply(text=answer)


@pytest.fixture
def api():
    return FakeApi()


@pytest.fixture
def policies():
    return FakePolicies()


@pytest.fixture
def make_agent(api, policies, tmp_path):
    def factory(replies, confirm_answer=False, max_rounds=5):
        llm = FakeLLM(replies)
        confirmer = Confirmer(confirm_answer)
        runner = ToolRunner(api, policies, STUDENT_NO, confirmer)
        agent = TuitionAgent(llm, runner, max_rounds=max_rounds)
        return agent, llm, confirmer

    return factory
