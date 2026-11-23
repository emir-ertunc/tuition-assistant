"""LLM wrapper.

The agent only talks to the small ChatModel interface below, so the tests can use a fake
model and Gemini can be swapped for another provider. GeminiChat keeps the conversation
history and turns the neutral tool specs into Gemini function declarations.

Automatic function calling of the google-genai sdk is turned off: the model only returns
which function it wants to call, and agent.py runs the tool and sends the result back.
"""

import re
import time
from dataclasses import dataclass, field
from typing import Protocol

from google import genai
from google.genai import errors, types


@dataclass
class ToolCall:
    name: str
    args: dict = field(default_factory=dict)
    call_id: str | None = None


@dataclass
class ModelReply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


@dataclass
class ToolResult:
    call: ToolCall
    response: dict


class ChatModel(Protocol):
    def send_message(self, text: str) -> ModelReply:
        """Send a user message, return the model's reply (text and/or tool calls)."""

    def send_tool_results(self, results: list[ToolResult], allow_tools: bool = True) -> ModelReply:
        """Send the results of the tool calls of the last reply.

        allow_tools=False forces a text answer (used when the tool round limit is reached).
        """


class LlmError(Exception):
    pass


RETRY_STATUS = {429, 500, 503}
REQUEST_TIMEOUT_MS = 60_000
MAX_RETRY_WAIT = 60
# on our network the tls handshake with googleapis sometimes fails a few times in a row
# ("[SSL: INVALID_SESSION_ID]") and then works again, so connection errors get more tries
CONNECTION_RETRIES = 5


def _retry_delay(exc: errors.APIError, attempt: int) -> float:
    # the free tier answers 429 with "Please retry in 44.8s", wait that long (max 60 s)
    match = re.search(r"retry in ([\d.]+)s", str(exc.message or exc))
    if exc.code == 429 and match:
        return min(float(match.group(1)) + 1, MAX_RETRY_WAIT)
    return 2 * (attempt + 1)


class GeminiChat:
    def __init__(self, api_key: str, model: str, system_prompt: str, tool_specs: list[dict],
                 client: genai.Client | None = None, retries: int = 2):
        # timeout in ms, without it a stuck request blocks the chat forever
        self._client = client or genai.Client(api_key=api_key,
                                              http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))
        self._model = model
        self._system_prompt = system_prompt
        self._tool = types.Tool(function_declarations=[
            types.FunctionDeclaration(
                name=spec["name"],
                description=spec["description"],
                parameters_json_schema=spec["parameters"],
            )
            for spec in tool_specs
        ])
        self._retries = retries
        self.history: list[types.Content] = []
        self._question_start = 0

    def send_message(self, text: str) -> ModelReply:
        self._question_start = len(self.history)
        self.history.append(types.Content(role="user", parts=[types.Part(text=text)]))
        return self._generate(allow_tools=True)

    def send_tool_results(self, results: list[ToolResult], allow_tools: bool = True) -> ModelReply:
        parts = [
            types.Part(function_response=types.FunctionResponse(
                id=result.call.call_id, name=result.call.name, response=result.response,
            ))
            for result in results
        ]
        self.history.append(types.Content(role="user", parts=parts))
        return self._generate(allow_tools=allow_tools)

    def _generate(self, allow_tools: bool) -> ModelReply:
        config = types.GenerateContentConfig(
            system_instruction=self._system_prompt,
            tools=[self._tool],
            tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(
                mode="AUTO" if allow_tools else "NONE",
            )),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        try:
            response = self._call_with_retry(config)
        except LlmError:
            # drop the failed question, otherwise the history ends with an unanswered
            # message or function call and every next request would fail too
            del self.history[self._question_start:]
            raise

        content = response.candidates[0].content if response.candidates else None
        if content is None or not content.parts:
            return ModelReply()
        # the whole content goes back into the history unchanged, newer gemini models need
        # the thought signatures of the function call parts in the next request
        self.history.append(content)

        texts, calls = [], []
        for part in content.parts:
            if part.function_call:
                fc = part.function_call
                calls.append(ToolCall(name=fc.name, args=dict(fc.args or {}), call_id=fc.id))
            elif part.text and not part.thought:
                texts.append(part.text)
        return ModelReply(text="".join(texts).strip(), tool_calls=calls)

    def _call_with_retry(self, config: types.GenerateContentConfig):
        api_errors = connection_errors = 0
        while True:
            try:
                return self._client.models.generate_content(
                    model=self._model, contents=self.history, config=config,
                )
            except errors.APIError as exc:
                if exc.code in RETRY_STATUS and api_errors < self._retries:
                    time.sleep(_retry_delay(exc, api_errors))
                    api_errors += 1
                    continue
                raise LlmError(f"Gemini request failed ({exc.code}): {exc.message}") from exc
            except Exception as exc:  # timeout, ssl or connection error
                if connection_errors < CONNECTION_RETRIES:
                    connection_errors += 1
                    time.sleep(connection_errors)  # 1, 2, 3 ... seconds
                    continue
                raise LlmError(f"Gemini request failed: {type(exc).__name__}: {exc}") from exc
