from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings

TOKEN_URL = "/api/v1/auth/token"


def test_login_success_returns_token_with_role(client):
    response = client.post(TOKEN_URL, data={"username": "20210001", "password": "student123"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "STUDENT"
    assert body["expires_in"] == settings.jwt_expire_minutes * 60

    claims = jwt.decode(body["access_token"], options={"verify_signature": False})
    assert claims["sub"] == "20210001"
    assert claims["studentNo"] == "20210001"


def test_login_wrong_password_returns_401(client):
    response = client.post(TOKEN_URL, data={"username": "admin", "password": "wrong"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_login_unknown_user_gives_same_error_as_wrong_password(client):
    response = client.post(TOKEN_URL, data={"username": "nobody", "password": "x"})

    assert response.status_code == 401
    assert response.json()["message"] == "wrong username or password"


def test_login_missing_fields_returns_400(client):
    response = client.post(TOKEN_URL, data={"username": "admin"})

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INPUT"


def test_me_returns_user_from_token(client, student_headers):
    response = client.get("/api/v1/auth/me", headers=student_headers)

    assert response.status_code == 200
    assert response.json() == {"username": "20210001", "role": "STUDENT", "studentNo": "20210001"}


def test_me_without_token_returns_401(client):
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_expired_token_returns_401(client):
    now = datetime.now(timezone.utc)
    expired = jwt.encode(
        {
            "sub": "20210001",
            "role": "STUDENT",
            "studentNo": "20210001",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "iat": now - timedelta(hours=2),
            "exp": now - timedelta(hours=1),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {expired}"})

    assert response.status_code == 401
    assert "expired" in response.json()["message"]


def test_token_signed_with_other_secret_returns_401(client):
    forged = jwt.encode(
        {
            "sub": "hacker",
            "role": "ADMIN",
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        },
        "a-different-secret-that-is-long-enough-for-hs256",
        algorithm="HS256",
    )
    response = client.get(
        "/api/v1/admin/tuitions/unpaid?term=2026-FALL",
        headers={"Authorization": f"Bearer {forged}"},
    )

    assert response.status_code == 401
