"""Agent loop tests: which tools run, what goes back to the LLM, payment confirmation."""

import json

from agent import TraceLog, build_system_prompt
from api_client import ApiError
from conftest import STUDENT_NO, call, calls, text


# ---------- the three scenarios of the assignment ----------

def test_policy_only_question_uses_mcp(make_agent, api, policies):
    agent, llm, _ = make_agent([
        call("search_tuition_policies", query="payment deadline"),
        text("The Fall 2026 deadline is September 30, 2026 (Section 2.1)."),
    ])

    result = agent.ask("When is the payment deadline?")

    assert result.tools_used == ["search_tuition_policies"]
    assert policies.queries == ["payment deadline"]
    assert api.query_calls == [] and api.pay_calls == []
    # the MCP result is what the LLM gets back
    name, response = llm.tool_results[0][0]
    assert name == "search_tuition_policies"
    assert response["ok"] is True
    assert response["data"]["matches"][0]["section"] == "3.1"
    assert "Section 2.1" in result.answer
    assert result.rounds == 1


def test_balance_question_uses_api_only(make_agent, api, policies):
    agent, llm, _ = make_agent([
        call("query_tuition"),
        text("Your balance is 5500.00 USD."),
    ])

    result = agent.ask("What is my balance?")

    assert result.tools_used == ["query_tuition"]
    assert api.query_calls == [(STUDENT_NO, None)]
    assert policies.queries == []
    response = llm.tool_results[0][0][1]
    assert response["data"]["balance"] == "5500.00"
    assert result.steps[0].summary.startswith(f"{STUDENT_NO} overall balance 5500.00")


def test_installment_question_uses_both_tools(make_agent, api, policies):
    agent, llm, _ = make_agent([
        calls(("query_tuition", {}), ("search_tuition_policies", {"query": "installments"})),
        text("Your balance is 5500.00 USD. You may request up to three installments (Section 3.2), "
             "subject to approval (Section 3.4)."),
    ])

    result = agent.ask("Can I pay my outstanding balance in installments?")

    assert sorted(result.tools_used) == ["query_tuition", "search_tuition_policies"]
    assert api.query_calls == [(STUDENT_NO, None)]
    assert policies.queries == ["installments"]
    # both results go back to the LLM in the same round
    assert [name for name, _ in llm.tool_results[0]] == ["query_tuition", "search_tuition_policies"]
    assert result.rounds == 1


def test_both_tools_in_separate_rounds(make_agent, api, policies):
    agent, llm, _ = make_agent([
        call("query_tuition", term="2026-FALL"),
        call("search_tuition_policies", query="installment eligibility"),
        text("..."),
    ])

    result = agent.ask("Can I pay my Fall balance in installments?")

    assert result.tools_used == ["query_tuition", "search_tuition_policies"]
    assert result.rounds == 2
    assert api.query_calls == [(STUDENT_NO, "2026-FALL")]


def test_no_tool_for_small_talk(make_agent, api, policies):
    agent, llm, _ = make_agent([text("Hello! Ask me about your tuition.")])

    result = agent.ask("hello")

    assert result.steps == [] and result.rounds == 0
    assert api.query_calls == [] and policies.queries == []


# ---------- payment confirmation ----------

def test_payment_declined_does_not_call_api(make_agent, api):
    agent, llm, confirmer = make_agent([
        call("pay_tuition", term="2026-FALL", amount=1000),
        text("No payment was made."),
    ], confirm_answer=False)

    result = agent.ask("Pay 1000 for 2026-FALL")

    assert api.pay_calls == []
    # the current balance was read before asking
    assert api.query_calls == [(STUDENT_NO, "2026-FALL")]
    preview = confirmer.previews[0]
    assert (preview.student_no, preview.term, preview.amount, preview.balance) == \
        (STUDENT_NO, "2026-FALL", "1000.00", "2500.00")
    response = llm.tool_results[0][0][1]
    assert response["ok"] is False
    assert response["error"]["code"] == "NOT_CONFIRMED"
    assert result.steps[0].ok is False


def test_payment_confirmed_calls_api(make_agent, api):
    agent, llm, confirmer = make_agent([
        call("pay_tuition", term="2026-FALL", amount=1000),
        text("Payment of 1000.00 USD was successful."),
    ], confirm_answer=True)

    agent.ask("Pay 1000 for 2026-FALL")

    assert len(confirmer.previews) == 1
    assert len(api.pay_calls) == 1
    sent = api.pay_calls[0]
    assert sent["studentNo"] == STUDENT_NO
    assert sent["term"] == "2026-FALL"
    assert sent["amount"] == "1000.00"
    assert sent["transactionId"].startswith("AGENT-")
    response = llm.tool_results[0][0][1]
    assert response["ok"] is True and response["data"]["status"] == "SUCCESS"


def test_every_payment_gets_a_new_transaction_id(make_agent, api):
    agent, _, _ = make_agent([
        call("pay_tuition", term="2026-FALL", amount=100), text("ok"),
        call("pay_tuition", term="2026-FALL", amount=100), text("ok"),
    ], confirm_answer=True)

    agent.ask("pay 100")
    agent.ask("pay 100 again")

    ids = [c["transactionId"] for c in api.pay_calls]
    assert len(ids) == 2 and ids[0] != ids[1]


def test_amount_over_balance_is_stopped_before_confirmation(make_agent, api):
    agent, llm, confirmer = make_agent([
        call("pay_tuition", term="2026-FALL", amount=9999),
        text("That is more than your balance."),
    ], confirm_answer=True)

    agent.ask("Pay 9999 for fall")

    assert confirmer.previews == [] and api.pay_calls == []
    assert llm.tool_results[0][0][1]["error"]["code"] == "AMOUNT_EXCEEDS_BALANCE"


def test_invalid_amount_is_rejected(make_agent, api):
    agent, llm, confirmer = make_agent([
        call("pay_tuition", term="2026-FALL", amount=-5),
        text("..."),
    ], confirm_answer=True)

    agent.ask("pay -5")

    assert confirmer.previews == [] and api.pay_calls == [] and api.query_calls == []
    assert llm.tool_results[0][0][1]["error"]["code"] == "INVALID_INPUT"


# ---------- student number comes from the login, not from the prompt ----------

def test_other_student_number_in_prompt_is_not_used(make_agent, api):
    # the model even tries to pass the other number as an argument
    agent, llm, _ = make_agent([
        call("query_tuition", studentNo="20210002", student_no="20210002"),
        text("I can only show your own account."),
    ])

    agent.ask("What is the balance of student 20210002?")

    assert api.query_calls == [(STUDENT_NO, None)]
    assert all(student != "20210002" for student, _ in api.query_calls)
    assert llm.tool_results[0][0][1]["data"]["studentNo"] == STUDENT_NO


def test_payment_for_other_student_goes_to_own_account(make_agent, api):
    agent, _, confirmer = make_agent([
        call("pay_tuition", term="2026-FALL", amount=100, studentNo="20210002"),
        text("..."),
    ], confirm_answer=True)

    agent.ask("Pay 100 for student 20210002")

    assert confirmer.previews[0].student_no == STUDENT_NO
    assert api.pay_calls[0]["studentNo"] == STUDENT_NO


def test_tool_definitions_have_no_student_number():
    from tools import TOOL_SPECS

    for spec in TOOL_SPECS:
        names = {p.lower() for p in spec["parameters"].get("properties", {})}
        assert not names & {"studentno", "student_no", "student", "studentnumber"}


# ---------- loop limit ----------

def test_loop_stops_after_max_rounds(make_agent, api):
    # the model keeps asking for tools; after 3 rounds it has to answer without tools
    replies = [call("query_tuition") for _ in range(4)] + [text("Here is what I found.")]
    agent, llm, _ = make_agent(replies, max_rounds=3)

    result = agent.ask("loop forever")

    assert result.rounds == 3
    assert len(api.query_calls) == 3  # the 4th request is not executed
    assert result.stopped_by_limit is True
    assert llm.allow_tools_flags == [True, True, True, False]
    assert llm.tool_results[-1][0][1]["error"]["code"] == "TOOL_LIMIT"
    assert result.answer == "Here is what I found."


def test_limit_with_empty_final_text_gives_fallback(make_agent):
    agent, _, _ = make_agent([call("query_tuition"), call("query_tuition"), text("")], max_rounds=1)

    result = agent.ask("?")

    assert result.stopped_by_limit
    assert "could not finish" in result.answer


# ---------- api / mcp errors go back to the LLM ----------

def test_api_error_is_sent_to_llm(make_agent, api):
    api.query_error = ApiError(401, "UNAUTHORIZED", "token expired")
    agent, llm, _ = make_agent([call("query_tuition"), text("Your session expired, please log in again.")])

    result = agent.ask("What is my balance?")

    response = llm.tool_results[0][0][1]
    assert response == {"ok": False, "error": {"status": 401, "code": "UNAUTHORIZED",
                                               "message": "token expired", "details": None}}
    assert result.steps[0].summary == "error 401 UNAUTHORIZED: token expired"


def test_payment_api_error_is_sent_to_llm(make_agent, api):
    api.pay_error = ApiError(409, "DUPLICATE_TRANSACTION", "transactionId was already used")
    agent, llm, _ = make_agent([call("pay_tuition", term="2026-FALL", amount=100), text("No payment was made.")],
                               confirm_answer=True)

    agent.ask("pay 100 for fall")

    error = llm.tool_results[0][0][1]["error"]
    assert (error["status"], error["code"]) == (409, "DUPLICATE_TRANSACTION")


def test_unknown_term_error(make_agent, api):
    agent, llm, _ = make_agent([call("query_tuition", term="2030-FALL"), text("...")])

    agent.ask("balance for 2030-FALL")

    assert llm.tool_results[0][0][1]["error"]["code"] == "NOT_FOUND"


def test_mcp_error_is_sent_to_llm(make_agent, policies):
    from mcp_client import PolicySearchError

    def broken(query, top_k=None):
        raise PolicySearchError("MCP server http://localhost:8001/mcp is not reachable")

    policies.search = broken
    agent, llm, _ = make_agent([call("search_tuition_policies", query="late fee"), text("...")])

    agent.ask("late fee?")

    error = llm.tool_results[0][0][1]["error"]
    assert error["code"] == "MCP_ERROR" and "not reachable" in error["message"]


def test_unknown_tool(make_agent):
    agent, llm, _ = make_agent([call("delete_everything"), text("...")])

    agent.ask("?")

    assert llm.tool_results[0][0][1]["error"]["code"] == "UNKNOWN_TOOL"


def test_llm_failure_gives_message():
    from agent import TuitionAgent
    from llm import LlmError

    class BrokenLLM:
        def send_message(self, text):
            raise LlmError("Gemini request failed (429): quota")

    result = TuitionAgent(BrokenLLM(), runner=None).ask("hi")

    assert "not available" in result.answer and result.error


# ---------- trace log and prompt ----------

def test_trace_is_written_as_json_lines(make_agent, tmp_path):
    agent, _, _ = make_agent([call("query_tuition"), text("5500.00 USD")])
    agent.trace_log = TraceLog(tmp_path, STUDENT_NO, "test-model")
    lines = []
    agent.echo = lines.append

    agent.ask("What is my balance?")

    files = list(tmp_path.glob("trace-*.jsonl"))
    assert len(files) == 1
    record = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
    assert record["question"] == "What is my balance?"
    assert record["toolsUsed"] == ["query_tuition"]
    assert record["steps"][0]["args"] == {}
    assert record["answer"] == "5500.00 USD"
    assert any("[tool] query_tuition" in line for line in lines)


def test_system_prompt_has_student_and_rules():
    prompt = build_system_prompt(STUDENT_NO, "Ali Yilmaz")
    assert STUDENT_NO in prompt
    assert "Section 3.4" in prompt and "Section 7.3" in prompt
    assert "search_tuition_policies" in prompt and "query_tuition" in prompt
