MOBILE = "/api/v1/mobile/tuitions"
BANKING = "/api/v1/banking/tuitions"


# ---------- mobile app (no auth, 3 per day) ----------

def test_mobile_query_returns_terms_and_overall_balance(client):
    response = client.get(f"{MOBILE}/20210003")

    assert response.status_code == 200
    body = response.json()
    assert body["studentNo"] == "20210003"
    assert body["tuitionTotal"] == "4000.00"
    assert body["paidAmount"] == "1000.00"
    assert body["balance"] == "3000.00"
    assert body["terms"][0]["term"] == "2026-FALL"
    assert body["terms"][0]["paymentDeadline"] == "2026-09-30"


def test_mobile_query_with_term_returns_only_that_term(client):
    response = client.get(f"{MOBILE}/20210001", params={"term": "2027-SPRING"})

    assert response.status_code == 200
    body = response.json()
    assert [t["term"] for t in body["terms"]] == ["2027-SPRING"]
    assert body["balance"] == "3000.00"


def test_mobile_query_unknown_student_returns_404(client):
    response = client.get(f"{MOBILE}/99999999")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_mobile_query_term_without_tuition_returns_404(client):
    response = client.get(f"{MOBILE}/20210002", params={"term": "2027-SPRING"})

    assert response.status_code == 404


def test_mobile_query_fourth_call_of_the_day_returns_429(client):
    for _ in range(3):
        assert client.get(f"{MOBILE}/20210004").status_code == 200

    response = client.get(f"{MOBILE}/20210004")

    assert response.status_code == 429
    assert response.json()["code"] == "QUERY_LIMIT_EXCEEDED"
    assert int(response.headers["Retry-After"]) > 0


def test_mobile_limit_is_counted_per_student(client):
    for _ in range(3):
        client.get(f"{MOBILE}/20210004")

    # another student still has their own 3 queries
    assert client.get(f"{MOBILE}/20210003").status_code == 200


def test_mobile_query_for_unknown_student_is_not_counted(client):
    client.get(f"{MOBILE}/99999999")
    for _ in range(3):
        assert client.get(f"{MOBILE}/20210004").status_code == 200


# ---------- banking app (auth) ----------

def test_bank_can_query_any_student(client, bank_headers):
    response = client.get(f"{BANKING}/20210003", headers=bank_headers)

    assert response.status_code == 200
    assert response.json()["balance"] == "3000.00"


def test_student_can_query_own_tuition(client, student_headers):
    response = client.get(f"{BANKING}/20210001", headers=student_headers)

    assert response.status_code == 200
    assert response.json()["balance"] == "6000.00"


def test_student_can_not_query_another_student(client, student_headers):
    # same case as a chat message like "what is the balance of 20210003?"
    response = client.get(f"{BANKING}/20210003", headers=student_headers)

    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_banking_query_without_token_returns_401(client):
    response = client.get(f"{BANKING}/20210001")

    assert response.status_code == 401


def test_admin_can_not_use_banking_query(client, admin_headers):
    response = client.get(f"{BANKING}/20210001", headers=admin_headers)

    assert response.status_code == 403


def test_banking_query_is_not_limited_like_mobile(client, bank_headers):
    for _ in range(5):
        assert client.get(f"{BANKING}/20210004", headers=bank_headers).status_code == 200
