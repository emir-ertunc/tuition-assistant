ADD = "/api/v1/admin/tuitions"
BATCH = "/api/v1/admin/tuitions/batch"
UNPAID = "/api/v1/admin/tuitions/unpaid"
HEADER = "studentNo,term,amount,currency\n"


def tuition(student_no="20210002", term="2027-SPRING", amount="2600.00", currency="USD"):
    return {"studentNo": student_no, "term": term, "amount": amount, "currency": currency}


def upload(client, headers, text, encoding="utf-8"):
    files = {"file": ("tuitions.csv", text.encode(encoding), "text/csv")}
    return client.post(BATCH, files=files, headers=headers)


# ---------- add tuition ----------

def test_add_new_tuition_returns_201(client, admin_headers):
    response = client.post(ADD, json=tuition(currency="usd"), headers=admin_headers)

    assert response.status_code == 201
    assert response.json() == {
        "status": "CREATED",
        "studentNo": "20210002",
        "term": "2027-SPRING",
        "amount": "2600.00",
        "currency": "USD",
    }


def test_add_existing_tuition_updates_it_and_returns_200(client, admin_headers):
    response = client.post(
        ADD, json=tuition(student_no="20210003", term="2026-FALL", amount="4500"), headers=admin_headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "UPDATED"

    unpaid = client.get(UNPAID, params={"term": "2026-FALL"}, headers=admin_headers).json()
    row = next(i for i in unpaid["items"] if i["studentNo"] == "20210003")
    assert row["tuitionTotal"] == "4500.00"
    assert row["balance"] == "3500.00"


def test_amount_lower_than_paid_amount_returns_409(client, admin_headers):
    # 20210003 already paid 1000 for 2026-FALL
    response = client.post(
        ADD, json=tuition(student_no="20210003", term="2026-FALL", amount="500"), headers=admin_headers
    )

    assert response.status_code == 409
    assert response.json()["code"] == "CONFLICT"


def test_currency_can_not_change_after_payment(client, admin_headers):
    response = client.post(
        ADD,
        json=tuition(student_no="20210003", term="2026-FALL", amount="4000", currency="EUR"),
        headers=admin_headers,
    )

    assert response.status_code == 409


def test_add_tuition_unknown_student_or_term_returns_404(client, admin_headers):
    assert client.post(ADD, json=tuition(student_no="99999999"), headers=admin_headers).status_code == 404
    assert client.post(ADD, json=tuition(term="2030-FALL"), headers=admin_headers).status_code == 404


def test_add_tuition_invalid_currency_returns_400(client, admin_headers):
    response = client.post(ADD, json=tuition(currency="DOLLAR"), headers=admin_headers)

    assert response.status_code == 400


def test_add_tuition_needs_admin_role(client, bank_headers, student_headers):
    assert client.post(ADD, json=tuition()).status_code == 401
    assert client.post(ADD, json=tuition(), headers=bank_headers).status_code == 403
    assert client.post(ADD, json=tuition(), headers=student_headers).status_code == 403


# ---------- add tuition batch ----------

def test_batch_all_rows_ok(client, admin_headers):
    text = HEADER + "20210002,2027-SPRING,2500,USD\n20210003,2027-SPRING,4000,USD\n"
    response = upload(client, admin_headers, text)

    assert response.status_code == 200
    assert response.json() == {
        "status": "COMPLETED",
        "totalRows": 2,
        "successCount": 2,
        "failureCount": 0,
        "errors": [],
    }


def test_batch_bad_rows_are_reported_and_good_rows_are_saved(client, admin_headers):
    text = (
        HEADER
        + "20210002,2027-SPRING,2500,USD\n"  # line 2 ok
        + "20210004,2027-SPRING,abc,USD\n"  # line 3 bad amount
        + "99999999,2027-SPRING,100,USD\n"  # line 4 unknown student
    )
    response = upload(client, admin_headers, text)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "PARTIAL"
    assert body["successCount"] == 1
    assert body["failureCount"] == 2
    assert [e["line"] for e in body["errors"]] == [3, 4]

    # the good row is really saved
    unpaid = client.get(UNPAID, params={"term": "2027-SPRING"}, headers=admin_headers).json()
    assert "20210002" in [i["studentNo"] for i in unpaid["items"]]


def test_batch_with_only_bad_rows_is_failed(client, admin_headers):
    response = upload(client, admin_headers, HEADER + "99999999,2027-SPRING,100,USD\n")

    assert response.json()["status"] == "FAILED"


def test_batch_wrong_header_returns_400(client, admin_headers):
    response = upload(client, admin_headers, "student,term,amount\n20210002,2027-SPRING,100\n")

    assert response.status_code == 400
    assert "header" in response.json()["message"]


def test_batch_without_rows_returns_400(client, admin_headers):
    assert upload(client, admin_headers, HEADER).status_code == 400


def test_batch_file_not_utf8_returns_400(client, admin_headers):
    text = HEADER + "20210002,2027-SPRING,2500,USD  ğüş\n"
    response = upload(client, admin_headers, text, encoding="utf-16")

    assert response.status_code == 400


def test_batch_needs_admin_role(client, bank_headers):
    text = HEADER + "20210002,2027-SPRING,2500,USD\n"
    assert upload(client, {}, text).status_code == 401
    assert upload(client, bank_headers, text).status_code == 403


# ---------- unpaid tuition status ----------

def test_unpaid_lists_only_students_with_balance(client, admin_headers):
    response = client.get(UNPAID, params={"term": "2026-FALL"}, headers=admin_headers)

    assert response.status_code == 200
    body = response.json()
    numbers = [i["studentNo"] for i in body["items"]]
    assert numbers == ["20210001", "20210003", "20210004"]  # 20210002 paid everything
    assert body["totalItems"] == 3


def test_unpaid_paging(client, admin_headers):
    first = client.get(UNPAID, params={"term": "2026-FALL", "pageSize": 2}, headers=admin_headers).json()
    second = client.get(
        UNPAID, params={"term": "2026-FALL", "page": 2, "pageSize": 2}, headers=admin_headers
    ).json()

    assert first["totalPages"] == 2
    assert len(first["items"]) == 2
    assert len(second["items"]) == 1
    assert second["items"][0]["studentNo"] == "20210004"


def test_unpaid_invalid_paging_returns_400(client, admin_headers):
    for params in [{"page": 0}, {"pageSize": 0}, {"pageSize": 101}]:
        response = client.get(UNPAID, params={"term": "2026-FALL", **params}, headers=admin_headers)
        assert response.status_code == 400


def test_unpaid_unknown_term_returns_404(client, admin_headers):
    response = client.get(UNPAID, params={"term": "2030-FALL"}, headers=admin_headers)

    assert response.status_code == 404


def test_unpaid_needs_admin_role(client, student_headers):
    response = client.get(UNPAID, params={"term": "2026-FALL"}, headers=student_headers)

    assert response.status_code == 403
