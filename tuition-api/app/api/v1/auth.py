from fastapi import APIRouter, Depends
from fastapi.security import OAuth2PasswordRequestForm

from app.api.deps import CurrentUser, get_auth_service, get_current_user
from app.api.errors import error_responses
from app.auth_service import AuthService
from app.schemas import CurrentUserResponse, TokenResponse

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/token",
    response_model=TokenResponse,
    summary="Log in and get a token",
    description=(
        "OAuth2 password flow. Send `username` and `password` as form data, use the returned "
        "`access_token` as `Authorization: Bearer <token>`. Swagger's **Authorize** button "
        "uses this endpoint."
    ),
    responses=error_responses(400, 401),
)
def login(
    form: OAuth2PasswordRequestForm = Depends(),
    service: AuthService = Depends(get_auth_service),
):
    return service.login(form.username, form.password)


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Who am I",
    description="Returns the user in the token. The agent uses it to find the student number.",
    responses=error_responses(401),
)
def me(user: CurrentUser = Depends(get_current_user)):
    return CurrentUserResponse(username=user.username, role=user.role, student_no=user.student_no)
