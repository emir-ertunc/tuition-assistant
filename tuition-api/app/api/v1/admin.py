from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from fastapi.concurrency import run_in_threadpool

from app.api.deps import get_tuition_service, require_roles
from app.api.errors import error_responses
from app.exceptions import InvalidInputError
from app.schemas import AddTuitionRequest, AddTuitionResult, BatchResult, UnpaidTuitionPage
from app.services import TuitionService

# every admin endpoint needs a token with the ADMIN role
router = APIRouter(
    prefix="/admin",
    tags=["University Web Site - Admin"],
    dependencies=[Depends(require_roles("ADMIN"))],
    responses=error_responses(401, 403),
)

MAX_CSV_SIZE = 1024 * 1024  # 1 MB is more than enough for this project


@router.post(
    "/tuitions",
    response_model=AddTuitionResult,
    summary="Add tuition",
    description=(
        "Creates the tuition of a student for a term. If the student already has a tuition for "
        "that term it is updated instead (201 = created, 200 = updated). The new amount can not "
        "be lower than what was already paid, and the currency can not change after a payment."
    ),
    responses={201: {"model": AddTuitionResult}, **error_responses(400, 404, 409)},
)
def add_tuition(
    request: AddTuitionRequest,
    response: Response,
    service: TuitionService = Depends(get_tuition_service),
):
    result = service.add_tuition(request.student_no, request.term, request.amount, request.currency)
    response.status_code = 201 if result.status == "CREATED" else 200
    return result


@router.post(
    "/tuitions/batch",
    response_model=BatchResult,
    summary="Add tuition - batch (CSV)",
    description=(
        "Upload a csv file with the header `studentNo,term,amount,currency`. Every row is "
        "processed like Add Tuition. Bad rows do not stop the good ones; the response has the "
        "success / failure counts and the line number + reason of each failed row."
    ),
    responses=error_responses(400),
)
async def add_tuition_batch(
    file: UploadFile = File(description="csv file"),
    service: TuitionService = Depends(get_tuition_service),
):
    content = await file.read(MAX_CSV_SIZE + 1)
    if len(content) > MAX_CSV_SIZE:
        raise InvalidInputError("csv file is too big (max 1 MB)")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidInputError("csv file must be utf-8")
    # the service uses the normal (blocking) db session, so run it in a worker thread
    return await run_in_threadpool(service.add_tuition_batch, text)


@router.get(
    "/tuitions/unpaid",
    response_model=UnpaidTuitionPage,
    summary="Unpaid tuition status",
    description="Paged list of students that still have a balance in the given term.",
    responses=error_responses(400, 404),
)
def get_unpaid_tuitions(
    term: str = Query(max_length=20, examples=["2026-FALL"]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100, alias="pageSize"),
    service: TuitionService = Depends(get_tuition_service),
):
    return service.get_unpaid_tuitions(term, page, page_size)
