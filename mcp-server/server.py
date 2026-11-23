"""MCP server for the university tuition policy document.

The policy file is split into sections and indexed (BM25) once, when this module
is loaded. Every tool call only searches the ready index.

Settings (environment variables or a .env file next to this script):
  MCP_HOST             default 127.0.0.1 (use 0.0.0.0 on Azure App Service)
  MCP_PORT             default 8001 (falls back to PORT if MCP_PORT is not set)
  POLICY_FILE          default data/University_Tuition_Policies.md
  MCP_ALLOWED_HOSTS    comma separated extra Host header values, e.g. my-app.azurewebsites.net
  MCP_ALLOWED_ORIGINS  comma separated extra Origin values, e.g. https://my-app.azurewebsites.net
  MCP_STATELESS        default true (no server side sessions, fine for several instances)
"""

import logging
import os
from pathlib import Path
from typing import Annotated, TypedDict

from dotenv import load_dotenv
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings

from indexer import MAX_TOP_K, PolicyIndex, PolicySearchError

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("tuition-policies")

LOCAL_HOSTS = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
LOCAL_ORIGINS = ["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"]


def _env_list(name: str) -> list[str]:
    return [v.strip() for v in os.getenv(name, "").split(",") if v.strip()]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def policy_file_path() -> Path:
    path = Path(os.getenv("POLICY_FILE", "data/University_Tuition_Policies.md"))
    return path if path.is_absolute() else BASE_DIR / path


def security_settings() -> TransportSecuritySettings | None:
    """Host/Origin checks against DNS rebinding.

    Without MCP_ALLOWED_HOSTS the SDK default is used (localhost only when bound
    to 127.0.0.1). When the server runs behind a public name, that name has to be
    listed, otherwise every request gets "421 Invalid Host header".
    """
    hosts = _env_list("MCP_ALLOWED_HOSTS")
    origins = _env_list("MCP_ALLOWED_ORIGINS")
    if not hosts and not origins:
        return None
    # also accept "name:port" for every listed name
    hosts = hosts + [h + ":*" for h in hosts if ":" not in h]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=LOCAL_HOSTS + hosts,
        allowed_origins=LOCAL_ORIGINS + origins,
    )


# --- build the index once at startup ---
POLICY_FILE = policy_file_path()
policy_index = PolicyIndex.from_file(POLICY_FILE)
log.info(
    "Indexed %s (%s): %d sections",
    policy_index.document, policy_index.document_id, len(policy_index.chunks),
)



class PolicyMatch(TypedDict):
    section: str
    heading: str
    parentHeading: str
    text: str
    score: float


class PolicySearchResult(TypedDict):
    document: str
    documentId: str
    query: str
    matches: list[PolicyMatch]


mcp = MCPServer(
    "tuition-policies",
    instructions=(
        "Search the university tuition policy document (deadlines, installments, late fees, "
        "scholarships, refunds, payment rules). It has general rules only, not student balances."
    ),
)


@mcp.tool(
    name="search_tuition_policies",
    description=(
        "Search the official university tuition policy document "
        f"({policy_index.document}, ID {policy_index.document_id}) and return the most relevant "
        "sections with their section number, heading and text. Use it for general policy "
        "questions: payment deadlines, installment plans, late fees, scholarships, refunds and "
        "withdrawals, payment posting time and payment confirmation rules. It does NOT know any "
        "student's balance, payments or scholarship status; use the Tuition REST API for those. "
        "Cite the returned section numbers in the answer."
    ),
)
def search_tuition_policies(
    query: Annotated[
        str,
        Field(description="Policy question or keywords in English, e.g. 'late fee for overdue tuition'."),
    ],
    top_k: Annotated[
        int,
        Field(ge=1, le=MAX_TOP_K, description=f"How many sections to return (1-{MAX_TOP_K})."),
    ] = 3,
) -> PolicySearchResult:
    try:
        result = policy_index.search(query, top_k)
    except PolicySearchError as e:
        raise ToolError(str(e)) from e
    log.info("search %r -> %s", result["query"], [m["section"] for m in result["matches"]])
    return result


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({
        "status": "ok",
        "document": policy_index.document,
        "documentId": policy_index.document_id,
        "sections": len(policy_index.chunks),
        "indexedAt": policy_index.built_at,
    })


def run_options() -> dict:
    port = os.getenv("MCP_PORT") or os.getenv("PORT") or "8001"
    return {
        "host": os.getenv("MCP_HOST", "127.0.0.1"),
        "port": int(port),
        "streamable_http_path": "/mcp",
        "stateless_http": _env_bool("MCP_STATELESS", True),
        "transport_security": security_settings(),
    }


if __name__ == "__main__":
    options = run_options()
    log.info("Starting MCP server on http://%s:%s/mcp", options["host"], options["port"])
    mcp.run(transport="streamable-http", **options)
