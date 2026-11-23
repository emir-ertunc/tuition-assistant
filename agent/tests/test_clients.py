"""Tests for the http client and the Gemini wrapper, without network."""

import json

import httpx
from google.genai import types

from api_client import ApiError, TuitionApiClient
from llm import GeminiChat, ToolCall, ToolResult
from tools import TOOL_SPECS

BASE = "http://gateway.test/api/v1"


def make_client(handler, key=""):
    return TuitionApiClient(BASE, key, http_client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_login_me_query_and_pay_requests():
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        path = request.url.path
        if path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "abc", "token_type": "bearer",
                                             "expires_in": 3600, "role": "STUDENT"})
        if path.endswith("/auth/me"):
            return httpx.Response(200, json={"username": "20210001", "role": "STUDENT", "studentNo": "20210001"})
        if path.endswith("/banking/payments"):
            return httpx.Response(201, json={"status": "SUCCESS"})
        return httpx.Response(200, json={"studentNo": "20210001", "terms": []})

    api = make_client(handler, key="sub-key")
    api.login("20210001", "pw")
    assert api.me()["studentNo"] == "20210001"
    api.query_tuition("20210001", "2026-FALL")
    api.pay_tuition("20210001", "2026-FALL", "100.00", "tx-1")

    login, me, query, pay = seen
    assert login.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert b"username=20210001" in login.content
    assert "authorization" not in login.headers
    for req in seen:
        assert req.headers["Ocp-Apim-Subscription-Key"] == "sub-key"
    assert me.headers["authorization"] == "Bearer abc"
    assert str(query.url) == f"{BASE}/banking/tuitions/20210001?term=2026-FALL"
    assert json.loads(pay.content) == {"studentNo": "20210001", "term": "2026-FALL",
                                       "amount": "100.00", "transactionId": "tx-1"}


def test_no_subscription_header_when_key_empty():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={})

    make_client(handler).me()
    assert "Ocp-Apim-Subscription-Key" not in seen[0].headers


def test_api_error_format_is_parsed():
    def handler(request):
        return httpx.Response(422, json={"code": "AMOUNT_EXCEEDS_BALANCE", "message": "too much", "details": None})

    try:
        make_client(handler).pay_tuition("20210001", "2026-FALL", "9999.00", "tx")
        raise AssertionError("ApiError expected")
    except ApiError as exc:
        assert (exc.status, exc.code, exc.message) == (422, "AMOUNT_EXCEEDS_BALANCE", "too much")


def test_gateway_error_with_other_body():
    def handler(request):
        return httpx.Response(401, json={"statusCode": 401, "message": "Access denied due to missing subscription key."})

    try:
        make_client(handler).me()
        raise AssertionError("ApiError expected")
    except ApiError as exc:
        assert exc.status == 401 and exc.code == "HTTP_401" and "subscription key" in exc.message


def test_unreachable_gateway():
    def handler(request):
        raise httpx.ConnectError("refused")

    try:
        make_client(handler).me()
        raise AssertionError("ApiError expected")
    except ApiError as exc:
        assert exc.status == 0 and exc.code == "GATEWAY_UNREACHABLE"


# ---------- Gemini wrapper with a fake sdk client ----------

class FakeModels:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def generate_content(self, model, contents, config):
        self.requests.append({"model": model, "contents": list(contents), "config": config})
        return self.responses.pop(0)


class FakeGenaiClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


def response_with(*parts):
    return types.GenerateContentResponse(candidates=[
        types.Candidate(content=types.Content(role="model", parts=list(parts)))
    ])


def test_gemini_wrapper_returns_tool_calls_and_sends_results():
    fake = FakeGenaiClient([
        response_with(types.Part(function_call=types.FunctionCall(id="c1", name="query_tuition", args={}))),
        response_with(types.Part(text="Your balance is 5500.00 USD.")),
    ])
    chat = GeminiChat("key", "gemini-test", "system", TOOL_SPECS, client=fake)

    reply = chat.send_message("What is my balance?")
    assert reply.tool_calls == [ToolCall(name="query_tuition", args={}, call_id="c1")]

    final = chat.send_tool_results([ToolResult(reply.tool_calls[0], {"ok": True, "data": {"balance": "5500.00"}})])
    assert final.text == "Your balance is 5500.00 USD." and final.tool_calls == []

    first, second = fake.models.requests
    config = first["config"]
    assert config.automatic_function_calling.disable is True
    assert config.tool_config.function_calling_config.mode == "AUTO"
    assert [d.name for d in config.tools[0].function_declarations] == [s["name"] for s in TOOL_SPECS]
    # history: user question, model function call, function response
    function_response = second["contents"][2].parts[0].function_response
    assert function_response.name == "query_tuition" and function_response.id == "c1"
    assert function_response.response == {"ok": True, "data": {"balance": "5500.00"}}


def test_gemini_wrapper_can_force_text_answer():
    fake = FakeGenaiClient([
        response_with(types.Part(function_call=types.FunctionCall(name="query_tuition", args={}))),
        response_with(types.Part(text="done")),
    ])
    chat = GeminiChat("key", "gemini-test", "system", TOOL_SPECS, client=fake)
    reply = chat.send_message("?")
    chat.send_tool_results([ToolResult(reply.tool_calls[0], {"ok": False})], allow_tools=False)

    assert fake.models.requests[1]["config"].tool_config.function_calling_config.mode == "NONE"


def test_gemini_failure_drops_the_failed_question():
    from google.genai import errors

    from llm import LlmError

    class FailingModels(FakeModels):
        def generate_content(self, model, contents, config):
            if len(self.requests) == 1:
                raise errors.APIError(400, {"error": {"code": 400, "message": "bad request", "status": "INVALID"}})
            return super().generate_content(model, contents, config)

    fake = FakeGenaiClient([])
    fake.models = FailingModels([
        response_with(types.Part(text="hi")),
        response_with(types.Part(text="second")),
    ])
    chat = GeminiChat("key", "gemini-test", "system", TOOL_SPECS, client=fake, retries=0)

    chat.send_message("first")
    try:
        chat.send_message("broken")
        raise AssertionError("LlmError expected")
    except LlmError:
        pass
    # only the first question and its answer are left, the next request starts clean
    assert [c.role for c in chat.history] == ["user", "model"]


class FlakyModels(FakeModels):
    """Fails the first `failures` calls with an ssl style connection error."""

    def __init__(self, responses, failures):
        super().__init__(responses)
        self.failures = failures
        self.calls = 0

    def generate_content(self, model, contents, config):
        self.calls += 1
        if self.calls <= self.failures:
            raise httpx.ConnectError("[SSL: INVALID_SESSION_ID] invalid session id")
        return super().generate_content(model, contents, config)


def test_gemini_retries_connection_errors(monkeypatch):
    import llm

    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    fake = FakeGenaiClient([])
    fake.models = FlakyModels([response_with(types.Part(text="ok"))], failures=3)
    chat = GeminiChat("key", "gemini-test", "system", TOOL_SPECS, client=fake)

    reply = chat.send_message("hello")

    assert reply.text == "ok"
    assert fake.models.calls == 4


def test_gemini_gives_up_after_too_many_connection_errors(monkeypatch):
    import llm
    from llm import LlmError

    monkeypatch.setattr(llm.time, "sleep", lambda seconds: None)
    fake = FakeGenaiClient([])
    fake.models = FlakyModels([response_with(types.Part(text="ok"))], failures=100)
    chat = GeminiChat("key", "gemini-test", "system", TOOL_SPECS, client=fake)

    try:
        chat.send_message("hello")
        raise AssertionError("LlmError expected")
    except LlmError as exc:
        assert "INVALID_SESSION_ID" in str(exc)
    assert fake.models.calls == llm.CONNECTION_RETRIES + 1
    assert chat.history == []
