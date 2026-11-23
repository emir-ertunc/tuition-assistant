# Tuition API

REST API for tuition operations (query tuition, pay tuition, add tuition, batch add,
unpaid tuition status). All routes are versioned under `/api/v1`.

## Endpoints

| Client | Operation | Method & route | Success |
|---|---|---|---|
| Mobile app | Query Tuition | `GET /api/v1/mobile/tuitions/{studentNo}?term=` | 200 |
| Banking app | Query Tuition | `GET /api/v1/banking/tuitions/{studentNo}?term=` | 200 |
| Banking app | Pay Tuition | `POST /api/v1/banking/payments` | 201 |
| Admin | Add Tuition | `POST /api/v1/admin/tuitions` | 201 created / 200 updated |
| Admin | Add Tuition – Batch | `POST /api/v1/admin/tuitions/batch` (csv file upload) | 200 |
| Admin | Unpaid Tuition Status | `GET /api/v1/admin/tuitions/unpaid?term=&page=&pageSize=` | 200 |

Query Tuition returns every term of the student plus the overall total; `term` is optional
and returns only that term.

## Authentication

JWT (HS256), OAuth2 password flow:

```
POST /api/v1/auth/token      (form data: username, password)  -> access_token
GET  /api/v1/auth/me         who is in the token
```

Send the token as `Authorization: Bearer <token>`. In Swagger use the **Authorize** button.

| Route group | Who can call it |
|---|---|
| `/api/v1/mobile/...` | everyone, no token (limited to 3 queries per student per day) |
| `/api/v1/banking/...` | `BANK` (any student) or `STUDENT` (only their own student number) |
| `/api/v1/admin/...` | `ADMIN` only |

The student number of a `STUDENT` user comes from the token (`studentNo` claim), not from
the request. So even if the AI Agent is asked about another student's number, the API
returns 403.

Token claims: `sub`, `role`, `studentNo` (students only), `iss`, `aud`, `iat`, `exp`
(valid for 60 minutes).

### Test accounts

Created by `python -m app.seed` (test passwords only):

| username | password | role |
|---|---|---|
| `admin` | `admin123` | ADMIN |
| `bank` | `bank123` | BANK |
| `20210001` … `20210004` | `student123` | STUDENT |

### Error format

Every error has the same body:

```json
{"code": "AMOUNT_EXCEEDS_BALANCE", "message": "amount 9999.00 is more than the remaining balance 2500.00", "details": null}
```

| HTTP | code | when |
|---|---|---|
| 400 | `INVALID_INPUT` | missing / wrong fields, bad csv, bad paging values |
| 401 | `UNAUTHORIZED` | no token, invalid / expired token, wrong password |
| 403 | `FORBIDDEN` | wrong role, or a student asking for another student's data |
| 404 | `NOT_FOUND` | student, term or tuition does not exist |
| 409 | `DUPLICATE_TRANSACTION` | transactionId was already used |
| 409 | `CONFLICT` | new tuition amount lower than paid amount, currency change after payment |
| 422 | `AMOUNT_EXCEEDS_BALANCE` | payment is more than the remaining balance |
| 429 | `QUERY_LIMIT_EXCEEDED` | 4th mobile query of the day (has a `Retry-After` header) |

## Run

```
cd tuition-api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Set `DATABASE_URL` in `.env`, then create the tables and the test data:

```
python -m app.seed
```

`python -m app.seed --reset` drops everything and seeds again.

Start the API:

```
uvicorn app.main:app --reload --port 8000
```

Swagger UI: http://localhost:8000/docs

## Unit tests

```
cd tuition-api
.venv\Scripts\activate
pytest
```

The tests do not need PostgreSQL, Azure or the LLM. Each test gets a fresh in-memory
SQLite database filled with the same seed data, and the api's `get_db` dependency is
replaced with it (`tests/conftest.py`). SQLite is only used here; the app runs on PostgreSQL.
Requests go through FastAPI's `TestClient`, so routing, validation, auth, business rules and
the error format are all tested together.

| Operation | File | Success cases | Failure / edge cases |
|---|---|---|---|
| Login, me | `test_auth.py` | token + claims, me | wrong password, unknown user, missing field, no token, expired token, token with other secret |
| Query Tuition (mobile) | `test_query_tuition.py` | all terms + overall, one term | unknown student, term without tuition, 4th call 429, limit per student, unknown student not counted |
| Query Tuition (banking) | `test_query_tuition.py` | bank any student, student own | student asks for another student 403, no token 401, admin 403 |
| Pay Tuition | `test_pay_tuition.py` | partial, full, student pays own | duplicate transactionId, amount > balance, already paid, 0 / negative, 3 decimals, missing fields, no tuition 404, other student 403, no token, admin 403 |
| Add Tuition | `test_admin.py` | create 201, update 200 | amount < paid, currency change, unknown student / term, bad currency, wrong role |
| Add Tuition – Batch | `test_admin.py` | all rows ok | partial with line numbers, all bad, wrong header, no rows, not utf-8, wrong role |
| Unpaid Tuition Status | `test_admin.py` | only unpaid, paging | bad page / pageSize, unknown term, wrong role |
| Service / helpers | `test_services.py` | money parsing, limit resets next day, batch duplicates, overall sum | invalid money values, unexpected error → 500 without details, unknown route |

Last run: **70 passed** – full output in [`docs/unit-test-results.txt`](../docs/unit-test-results.txt).
