"""Command line chat for the tuition assistant.

    python chat.py

Asks for the student's username and password, logs in through the gateway, then answers
questions. For every question the tool trace (tools, inputs, short results) is printed and
also written to logs/trace-<date>.jsonl.
"""

import sys
from getpass import getpass

from agent import TraceLog, TuitionAgent, build_system_prompt
from api_client import ApiError, TuitionApiClient
from config import load_settings
from llm import GeminiChat
from mcp_client import PolicySearchClient
from tools import TOOL_SPECS, PaymentPreview, ToolRunner

LOGIN_ATTEMPTS = 3


def confirm_payment(preview: PaymentPreview) -> bool:
    print()
    print("  +-------------------- Payment confirmation --------------------")
    print(f"  | Student          : {preview.student_no} {preview.full_name}")
    print(f"  | Term             : {preview.term}")
    print(f"  | Amount to pay    : {preview.amount} {preview.currency}")
    print(f"  | Current balance  : {preview.balance} {preview.currency}")
    print(f"  | Payment deadline : {preview.payment_deadline}")
    print("  +--------------------------------------------------------------")
    try:
        answer = input('  Type "yes" to send this payment, anything else cancels: ')
    except EOFError:
        return False
    confirmed = answer.strip().lower() == "yes"
    print("  payment confirmed, sending to the API" if confirmed else "  payment cancelled, nothing was sent")
    print()
    return confirmed


def login(api: TuitionApiClient) -> dict | None:
    for _ in range(LOGIN_ATTEMPTS):
        username = input("Username (student number): ").strip()
        password = getpass("Password: ")
        try:
            api.login(username, password)
            return api.me()
        except ApiError as exc:
            if exc.status == 401:
                print("Wrong username or password.\n")
                continue
            print(f"Login failed: {exc}")
            return None
    return None


def main():
    settings = load_settings()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is empty. Put your key from Google AI Studio into agent/.env")
        sys.exit(1)

    print("University Tuition Assistant")
    print(f"API gateway: {settings.gateway_base_url}")
    print(f"MCP server : {settings.mcp_server_url}")
    print(f"Model      : {settings.gemini_model}\n")

    api = TuitionApiClient(settings.gateway_base_url, settings.gateway_subscription_key)
    user = login(api)
    if user is None:
        sys.exit(1)
    if user.get("role") != "STUDENT" or not user.get("studentNo"):
        print("This chat is for students. Please log in with a student account.")
        sys.exit(1)

    student_no = user["studentNo"]
    full_name = ""
    try:
        full_name = api.query_tuition(student_no).get("fullName", "")
    except ApiError:
        pass  # the name is only used in the greeting and the system prompt

    runner = ToolRunner(api, PolicySearchClient(settings.mcp_server_url), student_no, confirm_payment)
    llm = GeminiChat(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        system_prompt=build_system_prompt(student_no, full_name),
        tool_specs=TOOL_SPECS,
    )
    agent = TuitionAgent(
        llm, runner,
        max_rounds=settings.max_tool_rounds,
        trace_log=TraceLog(settings.log_dir, student_no, settings.gemini_model),
        echo=print,
    )

    print(f"\nLogged in as {student_no} {full_name}. Ask a question (type 'exit' to quit).")
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit"):
            break
        print("Tool trace:")
        result = agent.ask(question)
        if not result.steps:
            print("  (no tool used)")
        print(f"\nAssistant: {result.answer}")

    api.close()


if __name__ == "__main__":
    main()
