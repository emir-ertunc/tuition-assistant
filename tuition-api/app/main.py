import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api import v1
from app.api.errors import error_body, register_error_handlers
from app.config import settings

DESCRIPTION = """
Tuition API of the university. Used by the mobile app, the banking app, the admin web site
and the AI Agent (always through the API Gateway).

* all routes are versioned: `/api/v1/...`
* json fields are camelCase, money values are strings with 2 decimals (`"3000.00"`)
* errors always have the same format: `{"code": "...", "message": "...", "details": [...]}`
"""

# when the api runs behind the gateway, swagger sends its requests to the gateway address
servers = [{"url": settings.public_base_url, "description": "API Gateway"}] if settings.public_base_url else None

app = FastAPI(
    title="Tuition API",
    version="1.0.0",
    description=DESCRIPTION,
    servers=servers,
)

register_error_handlers(app)
app.include_router(v1.router)


@app.middleware("http")
async def only_through_gateway(request: Request, call_next):
    # every /api call has to come through the gateway (it adds X-Gateway-Key).
    # /health, /docs and /openapi.json stay open.
    if settings.gateway_key and request.url.path.startswith("/api/"):
        sent = request.headers.get("X-Gateway-Key", "")
        if not secrets.compare_digest(sent, settings.gateway_key):
            return JSONResponse(
                status_code=403,
                content=error_body("FORBIDDEN", "requests must go through the API gateway"),
            )
    return await call_next(request)


@app.get("/health", tags=["health"])
def health():
    # just to check the service is running (also used by azure later)
    return {"status": "ok"}
