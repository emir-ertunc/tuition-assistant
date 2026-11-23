"""Shared test setup.

Tests do not need postgres, azure or the LLM. Every test gets a fresh in-memory sqlite
database with the same seed data as `python -m app.seed`, and the api's `get_db`
dependency is replaced with it. (SQLite is only used for the tests, the app itself runs on
PostgreSQL.)
"""

import functools

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import seed as seed_module
from app.database import Base, get_db
from app.main import app
from app.security import hash_password

# bcrypt is slow on purpose, hash every test password only once for the whole test run
seed_module.hash_password = functools.lru_cache(maxsize=None)(hash_password)


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # same in-memory db for every connection
    )

    # the python sqlite driver handles transactions itself, which breaks SAVEPOINT
    # (used by the batch upload). this is the fix from the sqlalchemy docs.
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, "begin")
    def _on_begin(conn):
        conn.exec_driver_sql("BEGIN")

    return engine


@pytest.fixture
def db_session():
    engine = _make_engine()
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    with TestingSession() as db:
        seed_module.seed(db)
        seed_module.seed_users(db)

    session = TestingSession()
    yield session
    session.close()
    engine.dispose()


@pytest.fixture
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _login(client, username, password):
    response = client.post(
        "/api/v1/auth/token", data={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def admin_headers(client):
    return _login(client, "admin", "admin123")


@pytest.fixture
def bank_headers(client):
    return _login(client, "bank", "bank123")


@pytest.fixture
def student_headers(client):
    # student 20210001: 2026-FALL 3000 and 2027-SPRING 3000, nothing paid
    return _login(client, "20210001", "student123")
