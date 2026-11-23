PAYMENTS = "/api/v1/banking/payments"


def payment(student_no="20210001", term="2026-FALL", amount="1000.00", tx="TX-1"):
    return {"studentNo": student_no, "term": term, "amount": amount, "transactionId": tx}


def test_partial_payment_reduces_balance(client, bank_headers):
    response = client.post(PAYMENTS, json=payment(amount="1000.00"), headers=bank_headers)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["paidAmount"] == "1000.00"
    assert body["totalPaid"] == "1000.00"
    assert body["remainingBalance"] == "2000.00"

    # the new balance is also returned by query tuition
    query = client.get("/api/v1/banking/tuitions/20210001?term=2026-FALL", headers=bank_headers)
    assert query.json()["balance"] == "2000.00"


def test_full_payment_makes_balance_zero(client, bank_headers):
    client.post(PAYMENTS, json=payment(amount="1000.00", tx="TX-1"), headers=bank_headers)
    response = client.post(PAYMENTS, json=payment(amount="2000.00", tx="TX-2"), headers=bank_headers)

    assert response.status_code == 201
    assert response.json()["remainingBalance"] == "0.00"


def test_student_can_pay_own_tuition(client, student_headers):
    response = client.post(PAYMENTS, json=payment(amount="500"), headers=student_headers)

    assert response.status_code == 201
    assert response.json()["remainingBalance"] == "2500.00"


def test_duplicate_transaction_id_is_rejected(client, bank_headers):
    first = client.post(PAYMENTS, json=payment(tx="SAME-TX"), headers=bank_headers)
    second = client.post(PAYMENTS, json=payment(tx="SAME-TX"), headers=bank_headers)

    assert first.status_code == 201
    assert second.status_code == 409
    assert second.json()["code"] == "DUPLICATE_TRANSACTION"

    # the balance was reduced only once
    query = client.get("/api/v1/banking/tuitions/20210001?term=2026-FALL", headers=bank_headers)
    assert query.json()["balance"] == "2000.00"


def test_seed_transaction_id_can_not_be_reused(client, bank_headers):
    response = client.post(
        PAYMENTS, json=payment(student_no="20210003", tx="SEED-TX-0002"), headers=bank_headers
    )

    assert response.status_code == 409


def test_amount_more_than_balance_is_rejected(client, bank_headers):
    response = client.post(PAYMENTS, json=payment(amount="3000.01"), headers=bank_headers)

    assert response.status_code == 422
    assert response.json()["code"] == "AMOUNT_EXCEEDS_BALANCE"


def test_payment_to_fully_paid_tuition_is_rejected(client, bank_headers):
    response = client.post(
        PAYMENTS, json=payment(student_no="20210002", amount="1"), headers=bank_headers
    )

    assert response.status_code == 422


def test_zero_or_negative_amount_returns_400(client, bank_headers):
    for amount in ["0", "-50"]:
        response = client.post(PAYMENTS, json=payment(amount=amount), headers=bank_headers)
        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_INPUT"


def test_amount_with_three_decimals_returns_400(client, bank_headers):
    response = client.post(PAYMENTS, json=payment(amount="10.555"), headers=bank_headers)

    assert response.status_code == 400


def test_missing_fields_are_listed_in_details(client, bank_headers):
    response = client.post(PAYMENTS, json={"studentNo": "20210001"}, headers=bank_headers)

    assert response.status_code == 400
    details = " ".join(response.json()["details"])
    assert "term" in details and "amount" in details and "transactionId" in details


def test_payment_for_term_without_tuition_returns_404(client, bank_headers):
    response = client.post(
        PAYMENTS, json=payment(student_no="20210002", term="2027-SPRING"), headers=bank_headers
    )

    assert response.status_code == 404


def test_student_can_not_pay_for_another_student(client, student_headers):
    response = client.post(
        PAYMENTS, json=payment(student_no="20210003"), headers=student_headers
    )

    assert response.status_code == 403


def test_payment_without_token_returns_401(client):
    response = client.post(PAYMENTS, json=payment())

    assert response.status_code == 401


def test_admin_can_not_pay(client, admin_headers):
    response = client.post(PAYMENTS, json=payment(), headers=admin_headers)

    assert response.status_code == 403
