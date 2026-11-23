from dataclasses import dataclass

import jwt
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.auth_service import AuthService
from app.database import get_db
from app.exceptions import AuthenticationError, ForbiddenError
from app.security import decode_access_token
from app.services import TuitionService, TuitionServiceImpl

# auto_error=False so we can return our own error format instead of fastapi's
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)


def get_tuition_service(db: Session = Depends(get_db)) -> TuitionService:
    # routers only know the interface, tests can override this function with a fake
    return TuitionServiceImpl(db)


def get_auth_service(db: Session = Depends(get_db)) -> AuthService:
    return AuthService(db)


@dataclass
class CurrentUser:
    username: str
    role: str
    student_no: str | None


def get_current_user(token: str | None = Depends(oauth2_scheme)) -> CurrentUser:
    if not token:
        raise AuthenticationError("bearer token is missing")
    try:
        claims = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise AuthenticationError("token has expired, please log in again")
    except jwt.InvalidTokenError:
        raise AuthenticationError("token is not valid")
    return CurrentUser(
        username=claims["sub"], role=claims["role"], student_no=claims.get("studentNo")
    )


def require_roles(*roles: str):
    def checker(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in roles:
            raise ForbiddenError(f"this operation needs one of these roles: {', '.join(roles)}")
        return user

    return checker


def check_student_access(user: CurrentUser, student_no: str) -> None:
    # a student can only see or pay their own tuition. the number in the request
    # (or in a chat message) does not matter, the one in the token does.
    if user.role == "STUDENT" and user.student_no != student_no:
        raise ForbiddenError("students can only access their own tuition")
