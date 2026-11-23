from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import get_tuition_service
from app.api.errors import error_responses
from app.schemas import TuitionQueryResult
from app.services import TuitionService

router = APIRouter(prefix="/mobile", tags=["University Mobile App"])


@router.get(
    "/tuitions/{studentNo}",
    response_model=TuitionQueryResult,
    summary="Query tuition (mobile app)",
    description=(
        "Returns the tuition total and the current balance of the student, per term and overall. "
        "Give `term` to get only one term. No authentication. "
        "Limited to **3 calls per student per day** (counted by student number, resets at "
        "00:00 UTC). The 4th call returns 429."
    ),
    responses=error_responses(400, 404, 429),
)
def query_tuition_mobile(
    student_no: str = Path(alias="studentNo", max_length=20, examples=["20210001"]),
    term: str | None = Query(default=None, max_length=20, examples=["2026-FALL"]),
    service: TuitionService = Depends(get_tuition_service),
):
    return service.query_tuition_mobile(student_no, term)
