from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import CurrentUser, check_student_access, get_tuition_service, require_roles
from app.api.errors import error_responses
from app.schemas import PaymentResult, PayTuitionRequest, TuitionQueryResult
from app.services import TuitionService

router = APIRouter(prefix="/banking", tags=["Banking App"])

# BANK can work with any student, STUDENT (used by the AI Agent) only with their own number
allowed_users = require_roles("BANK", "STUDENT")


@router.get(
    "/tuitions/{studentNo}",
    response_model=TuitionQueryResult,
    summary="Query tuition (banking app)",
    description=(
        "Returns the tuition total and the current balance of the student, per term and overall. "
        "Give `term` to get only one term. Needs a token with role BANK or STUDENT; "
        "a STUDENT can only query their own number."
    ),
    responses=error_responses(400, 401, 403, 404),
)
def query_tuition(
    student_no: str = Path(alias="studentNo", max_length=20, examples=["20210001"]),
    term: str | None = Query(default=None, max_length=20, examples=["2026-FALL"]),
    user: CurrentUser = Depends(allowed_users),
    service: TuitionService = Depends(get_tuition_service),
):
    check_student_access(user, student_no)
    return service.query_tuition(student_no, term)


@router.post(
    "/payments",
    response_model=PaymentResult,
    status_code=201,
    summary="Pay tuition",
    description=(
        "Records a simulated full or partial payment (no real card processing). "
        "Needs a token with role BANK or STUDENT; a STUDENT can only pay their own tuition. "
        "Rejected if the `transactionId` was used before (409) or the amount is more than the "
        "remaining balance (422)."
    ),
    responses=error_responses(400, 401, 403, 404, 409, 422),
)
def pay_tuition(
    request: PayTuitionRequest,
    user: CurrentUser = Depends(allowed_users),
    service: TuitionService = Depends(get_tuition_service),
):
    check_student_access(user, request.student_no)
    return service.pay_tuition(
        request.student_no,
        request.term,
        request.amount,
        request.transaction_id,
        channel=user.role,  # BANK or STUDENT
    )
