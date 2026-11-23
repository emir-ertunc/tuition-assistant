"""Turns errors into one json format for every endpoint:

    {"code": "NOT_FOUND", "message": "student 99999999 not found", "details": null}
"""

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.exceptions import (
    AmountExceedsBalanceError,
    AuthenticationError,
    ConflictError,
    DuplicateTransactionError,
    ForbiddenError,
    InvalidInputError,
    NotFoundError,
    QueryLimitExceededError,
    TuitionError,
)
from app.schemas import ErrorResponse

STATUS_CODES = {
    AuthenticationError: 401,
    ForbiddenError: 403,
    InvalidInputError: 400,
    NotFoundError: 404,
    ConflictError: 409,
    DuplicateTransactionError: 409,
    AmountExceedsBalanceError: 422,
    QueryLimitExceededError: 429,
}


def error_body(code: str, message: str, details: list[str] | None = None) -> dict:
    return ErrorResponse(code=code, message=message, details=details).model_dump(mode="json")


def seconds_until_utc_midnight() -> int:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((tomorrow - now).total_seconds())


async def tuition_error_handler(request: Request, exc: TuitionError):
    status = STATUS_CODES.get(type(exc), 400)
    headers = None
    if isinstance(exc, QueryLimitExceededError):
        headers = {"Retry-After": str(seconds_until_utc_midnight())}
    elif isinstance(exc, AuthenticationError):
        headers = {"WWW-Authenticate": "Bearer"}
    return JSONResponse(status_code=status, content=error_body(exc.code, exc.message), headers=headers)


async def http_error_handler(request: Request, exc: StarletteHTTPException):
    # unknown route, wrong method etc. also in our format
    codes = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(codes.get(exc.status_code, "HTTP_ERROR"), str(exc.detail)),
        headers=getattr(exc, "headers", None),
    )


async def validation_error_handler(request: Request, exc: RequestValidationError):
    # fastapi returns 422 with its own format, we use 400 and our format instead
    details = []
    for err in exc.errors():
        field = ".".join(str(p) for p in err["loc"] if p != "body")
        details.append(f"{field}: {err['msg']}")
    return JSONResponse(
        status_code=400,
        content=error_body("INVALID_INPUT", "request is not valid", details),
    )


async def unexpected_error_handler(request: Request, exc: Exception):
    # do not send stack traces to the client
    return JSONResponse(status_code=500, content=error_body("INTERNAL_ERROR", "something went wrong"))


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(TuitionError, tuition_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(Exception, unexpected_error_handler)


# used in the routers so swagger shows the error format
def error_responses(*codes: int) -> dict:
    return {code: {"model": ErrorResponse} for code in codes}
