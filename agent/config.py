"""Settings read from the environment (.env file next to this module)."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_MODEL = "gemini-3.6-flash"
DEFAULT_GATEWAY_URL = "http://localhost:8000/api/v1"
DEFAULT_MCP_URL = "http://localhost:8001/mcp"
DEFAULT_MAX_TOOL_ROUNDS = 5


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str
    gemini_model: str
    gateway_base_url: str
    gateway_subscription_key: str
    mcp_server_url: str
    max_tool_rounds: int
    log_dir: Path


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name, "").strip()
    if not value:
        return default
    try:
        return max(1, int(value))
    except ValueError:
        return default


def load_settings() -> Settings:
    load_dotenv(BASE_DIR / ".env")
    log_dir = Path(os.getenv("AGENT_LOG_DIR", "").strip() or BASE_DIR / "logs")
    return Settings(
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "").strip() or DEFAULT_MODEL,
        gateway_base_url=(os.getenv("GATEWAY_BASE_URL", "").strip() or DEFAULT_GATEWAY_URL).rstrip("/"),
        gateway_subscription_key=os.getenv("GATEWAY_SUBSCRIPTION_KEY", "").strip(),
        mcp_server_url=os.getenv("MCP_SERVER_URL", "").strip() or DEFAULT_MCP_URL,
        max_tool_rounds=_int_env("AGENT_MAX_TOOL_ROUNDS", DEFAULT_MAX_TOOL_ROUNDS),
        log_dir=log_dir,
    )
