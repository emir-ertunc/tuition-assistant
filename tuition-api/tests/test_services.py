"""Tests for the service layer and helpers without going through http."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_tuition_service
from app.exceptions import InvalidInputError, QueryLimitExceededError
from app.main import app
from app.services import TuitionServiceImpl, parse_money


# ---------- parse_money ----------

@pytest.mark.parametrize(
    "value, expected",
    [("1000", "1000.00"), ("10.5", "10.50"), (" 99.99 ", "99.99"), (250, "250.00")],
)
def test_parse_money_valid_values(value, expected):
    assert parse_money(value) == Decimal(expected)


@pytest.mark.parametrize("value", ["abc", "", "10.555", "NaN", "Infinity", None])
def test_parse_money_invalid_values(value):
    with pytest.raises(InvalidInputError):
        parse_money(value)


# ---------- service ----------

def test_mobile_limit_resets_next_day(db_session):
    service = TuitionServiceImpl(db_session)
    day = date(2026, 11, 23)

    for _ in range(3):
        service.query_tuition_mobile("20210004", today=day)
    with pytest.raises(QueryLimitExceededError):
        service.query_tuition_mobile("20210004", today=day)

    result = service.query_tuition_mobile("20210004", today=date(2026, 11, 24))
    assert result.balance == Decimal("250.00")


def test_batch_same_student_twice_keeps_last_row(db_session):
    service = TuitionServiceImpl(db_session)
    csv_text = (
        "studentNo,term,amount,currency\n"
        "20210002,2027-SPRING,2000,USD\n"
        "20210002,2027-SPRING,2200,USD\n"
    )

    result = service.add_tuition_batch(csv_text)

    assert result.success_count == 2
    spring = service.query_tuition("20210002", "2027-SPRING")
    assert spring.tuition_total == Decimal("2200.00")


def test_query_tuition_overall_is_sum_of_terms(db_session):
    result = TuitionServiceImpl(db_session).query_tuition("20210001")

    assert len(result.terms) == 2
    assert result.tuition_total == sum(t.tuition_total for t in result.terms)
    assert result.balance == Decimal("6000.00")


# ---------- api with a fake service ----------

class BrokenService:
    def query_tuition_mobile(self, student_no, term=None, today=None):
        raise RuntimeError("database is down")


def test_unexpected_error_returns_500_without_details():
    app.dependency_overrides[get_tuition_service] = lambda: BrokenService()
    try:
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/api/v1/mobile/tuitions/20210001")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "database is down" not in response.text


def test_unknown_route_uses_error_format(client):
    response = client.get("/api/v1/nothing-here")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"
