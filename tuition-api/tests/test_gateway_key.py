"""When GATEWAY_KEY is set (on azure), /api calls without the gateway header are refused."""

import pytest

from app.config import settings


@pytest.fixture
def gateway_key(monkeypatch):
    monkeypatch.setattr(settings, "gateway_key", "test-gateway-key")
    return "test-gateway-key"


def test_request_with_gateway_header_is_accepted(client, gateway_key):
    response = client.get("/api/v1/mobile/tuitions/20210003", headers={"X-Gateway-Key": gateway_key})

    assert response.status_code == 200


def test_direct_request_without_gateway_header_returns_403(client, gateway_key):
    response = client.get("/api/v1/mobile/tuitions/20210003")

    assert response.status_code == 403
    assert response.json()["message"] == "requests must go through the API gateway"


def test_wrong_gateway_header_returns_403(client, gateway_key):
    response = client.get("/api/v1/mobile/tuitions/20210003", headers={"X-Gateway-Key": "wrong"})

    assert response.status_code == 403


def test_health_does_not_need_gateway_header(client, gateway_key):
    assert client.get("/health").status_code == 200


def test_check_is_off_when_no_key_is_set(client):
    # local development and the other tests run without a gateway
    assert client.get("/api/v1/mobile/tuitions/20210003").status_code == 200
