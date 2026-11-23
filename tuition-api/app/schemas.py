"""DTOs used by the service layer and the api.

Database models are never returned directly, so we only send the fields the client needs.
In python the fields are snake_case, in json they are camelCase (studentNo, transactionId ...)
to match the names in the assignment and the csv file.
Money values are Decimal, in json they are written as strings like "3000.00".
"""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        validate_by_name=True,
        validate_by_alias=True,
        serialize_by_alias=True,
    )


# ---------- requests ----------

class PayTuitionRequest(CamelModel):
    student_no: str = Field(min_length=1, max_length=20, examples=["20210001"])
    term: str = Field(min_length=1, max_length=20, examples=["2026-FALL"])
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["1000.00"])
    transaction_id: str = Field(
        min_length=1,
        max_length=64,
        examples=["BANK-2026-000123"],
        description="Unique id sent by the client. The same id is never processed twice.",
    )


class AddTuitionRequest(CamelModel):
    student_no: str = Field(min_length=1, max_length=20, examples=["20210001"])
    term: str = Field(min_length=1, max_length=20, examples=["2027-SPRING"])
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2, examples=["3000.00"])
    currency: str = Field(pattern=r"^[A-Za-z]{3}$", examples=["USD"])


# ---------- auth ----------

class TokenResponse(BaseModel):
    # snake_case on purpose: the oauth2 standard (and the swagger authorize button)
    # expects access_token and token_type
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str


class CurrentUserResponse(CamelModel):
    username: str
    role: str
    student_no: str | None = None


# ---------- responses ----------

class ErrorResponse(CamelModel):
    code: str = Field(examples=["NOT_FOUND"])
    message: str = Field(examples=["student 99999999 not found"])
    details: list[str] | None = None


class TermBalance(CamelModel):
    term: str
    tuition_total: Decimal
    paid_amount: Decimal
    balance: Decimal
    currency: str
    payment_deadline: date


class TuitionQueryResult(CamelModel):
    student_no: str
    full_name: str
    terms: list[TermBalance]
    # overall values (sum of the terms above)
    tuition_total: Decimal
    paid_amount: Decimal
    balance: Decimal


class PaymentResult(CamelModel):
    status: str
    transaction_id: str
    student_no: str
    term: str
    paid_amount: Decimal  # amount of this payment
    total_paid: Decimal  # all payments for this term
    remaining_balance: Decimal


class AddTuitionResult(CamelModel):
    status: str  # CREATED or UPDATED
    student_no: str
    term: str
    amount: Decimal
    currency: str


class BatchRowError(CamelModel):
    line: int
    message: str


class BatchResult(CamelModel):
    status: str  # COMPLETED, PARTIAL or FAILED
    total_rows: int
    success_count: int
    failure_count: int
    errors: list[BatchRowError]


class UnpaidTuitionItem(CamelModel):
    student_no: str
    full_name: str
    tuition_total: Decimal
    paid_amount: Decimal
    balance: Decimal
    currency: str


class UnpaidTuitionPage(CamelModel):
    term: str
    page: int
    page_size: int
    total_items: int
    total_pages: int
    items: list[UnpaidTuitionItem]
