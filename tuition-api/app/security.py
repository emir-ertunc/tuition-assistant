"""Password hashing and JWT helpers."""

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.config import settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        # bcrypt does not accept passwords longer than 72 bytes
        return False


def create_access_token(username: str, role: str, student_no: str | None) -> tuple[str, int]:
    """Returns the token and how many seconds it is valid."""
    now = datetime.now(timezone.utc)
    expires_in = settings.jwt_expire_minutes * 60
    claims = {
        "sub": username,
        "role": role,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
    }
    if student_no:
        # the gateway uses this claim for the per student limit
        claims["studentNo"] = student_no
    token = jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str) -> dict:
    """Raises jwt.InvalidTokenError (or ExpiredSignatureError) if the token is not ok."""
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["exp", "sub", "role"]},
    )
