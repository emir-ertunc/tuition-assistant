"""Business logic of the tuition api.

TuitionService is the interface, TuitionServiceImpl is the real one that uses the database.
Controllers will only depend on the interface, so it can be replaced with a fake in tests.
"""

import csv
import io
import math
import re
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.exceptions import (
    AmountExceedsBalanceError,
    ConflictError,
    DuplicateTransactionError,
    InvalidInputError,
    NotFoundError,
    QueryLimitExceededError,
    TuitionError,
)
from app.models import Payment, Student, Tuition, TuitionQueryLog
from app.repositories import (
    PaymentRepository,
    QueryLogRepository,
    StudentRepository,
    TermRepository,
    TuitionRepository,
)
from app.schemas import (
    AddTuitionResult,
    BatchResult,
    BatchRowError,
    PaymentResult,
    TermBalance,
    TuitionQueryResult,
    UnpaidTuitionItem,
    UnpaidTuitionPage,
)

MAX_MOBILE_QUERIES_PER_DAY = 3
MAX_PAGE_SIZE = 100
CSV_COLUMNS = ["studentNo", "term", "amount", "currency"]
CENT = Decimal("0.01")


def parse_money(value, field: str = "amount") -> Decimal:
    """Turns the input into a Decimal with 2 decimals, rejects things like 10.555 or 'abc'."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise InvalidInputError(f"{field} is not a valid number")
    if not number.is_finite():
        raise InvalidInputError(f"{field} is not a valid number")
    if number.as_tuple().exponent < -2:
        raise InvalidInputError(f"{field} can have at most 2 decimals")
    return number.quantize(CENT)


def utc_today() -> date:
    # the daily limit resets at midnight utc (same on the server and on azure)
    return datetime.now(timezone.utc).date()


class TuitionService(ABC):
    @abstractmethod
    def query_tuition(self, student_no: str, term: str | None = None) -> TuitionQueryResult: ...

    @abstractmethod
    def query_tuition_mobile(
        self, student_no: str, term: str | None = None, today: date | None = None
    ) -> TuitionQueryResult: ...

    @abstractmethod
    def pay_tuition(
        self, student_no: str, term: str, amount, transaction_id: str, channel: str = "BANK"
    ) -> PaymentResult: ...

    @abstractmethod
    def add_tuition(self, student_no: str, term: str, amount, currency: str) -> AddTuitionResult: ...

    @abstractmethod
    def add_tuition_batch(self, csv_text: str) -> BatchResult: ...

    @abstractmethod
    def get_unpaid_tuitions(self, term: str, page: int = 1, page_size: int = 20) -> UnpaidTuitionPage: ...


class TuitionServiceImpl(TuitionService):
    def __init__(self, db: Session):
        self.db = db
        self.students = StudentRepository(db)
        self.terms = TermRepository(db)
        self.tuitions = TuitionRepository(db)
        self.payments = PaymentRepository(db)
        self.query_logs = QueryLogRepository(db)

    # ---------- query tuition ----------

    def query_tuition(self, student_no, term=None):
        student = self._get_student(student_no)
        tuitions = self.tuitions.list_for_student(student.id)

        if term:
            tuitions = [t for t in tuitions if t.term_code == term]
            if not tuitions:
                raise NotFoundError(f"no tuition found for student {student_no} in term {term}")

        terms = [
            TermBalance(
                term=t.term_code,
                tuition_total=t.amount,
                paid_amount=t.paid_amount,
                balance=t.balance,
                currency=t.currency,
                payment_deadline=t.term.payment_deadline,
            )
            for t in tuitions
        ]
        return TuitionQueryResult(
            student_no=student.student_no,
            full_name=student.full_name,
            terms=terms,
            tuition_total=sum((t.tuition_total for t in terms), Decimal("0.00")),
            paid_amount=sum((t.paid_amount for t in terms), Decimal("0.00")),
            balance=sum((t.balance for t in terms), Decimal("0.00")),
        )

    def query_tuition_mobile(self, student_no, term=None, today=None):
        """Same as query_tuition but limited to 3 calls per student per day."""
        student = self._get_student(student_no)
        day = today or utc_today()

        try:
            log = self.query_logs.get(student.id, day)
            if log is None:
                log = TuitionQueryLog(student_id=student.id, query_date=day, query_count=0)
                self.query_logs.add(log)
            if log.query_count >= MAX_MOBILE_QUERIES_PER_DAY:
                raise QueryLimitExceededError(
                    f"daily limit of {MAX_MOBILE_QUERIES_PER_DAY} tuition queries reached "
                    f"for student {student_no}, try again tomorrow"
                )
            log.query_count += 1
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        return self.query_tuition(student_no, term)

    # ---------- pay tuition ----------

    def pay_tuition(self, student_no, term, amount, transaction_id, channel="BANK"):
        amount = parse_money(amount)
        if amount <= 0:
            raise InvalidInputError("amount must be greater than 0")
        transaction_id = (transaction_id or "").strip()
        if not transaction_id or len(transaction_id) > 64:
            raise InvalidInputError("transaction_id is required (max 64 characters)")

        try:
            student = self._get_student(student_no)
            tuition = self.tuitions.get(student.id, term, lock=True)
            if tuition is None:
                raise NotFoundError(f"no tuition found for student {student_no} in term {term}")

            if self.payments.exists(transaction_id):
                raise DuplicateTransactionError(
                    f"transaction {transaction_id} was already processed"
                )

            balance = tuition.balance
            if amount > balance:
                raise AmountExceedsBalanceError(
                    f"amount {amount} is more than the remaining balance {balance}"
                )

            self.payments.add(
                Payment(
                    tuition_id=tuition.id,
                    transaction_id=transaction_id,
                    amount=amount,
                    status="COMPLETED",
                    channel=channel,
                )
            )
            tuition.paid_amount += amount
            self.db.commit()
        except IntegrityError:
            # two requests with the same transaction id at the same time
            self.db.rollback()
            raise DuplicateTransactionError(f"transaction {transaction_id} was already processed")
        except Exception:
            self.db.rollback()
            raise

        return PaymentResult(
            status="SUCCESS",
            transaction_id=transaction_id,
            student_no=student.student_no,
            term=term,
            paid_amount=amount,
            total_paid=tuition.paid_amount,
            remaining_balance=tuition.balance,
        )

    # ---------- add tuition ----------

    def add_tuition(self, student_no, term, amount, currency):
        try:
            result = self._upsert_tuition(student_no, term, amount, currency)
            self.db.commit()
            return result
        except Exception:
            self.db.rollback()
            raise

    def add_tuition_batch(self, csv_text):
        reader = csv.DictReader(io.StringIO((csv_text or "").lstrip("﻿")))
        header = [c.strip() for c in (reader.fieldnames or [])]
        if header != CSV_COLUMNS:
            raise InvalidInputError("csv header must be: " + ",".join(CSV_COLUMNS))
        reader.fieldnames = header

        total = success = 0
        errors = []
        try:
            for row in reader:
                total += 1
                values = {c: (row.get(c) or "").strip() for c in CSV_COLUMNS}
                try:
                    # savepoint per row, a bad row does not cancel the good ones
                    with self.db.begin_nested():
                        self._upsert_tuition(
                            values["studentNo"], values["term"], values["amount"], values["currency"]
                        )
                    success += 1
                except TuitionError as e:
                    errors.append(BatchRowError(line=reader.line_num, message=e.message))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        if total == 0:
            raise InvalidInputError("csv file has no data rows")

        if not errors:
            status = "COMPLETED"
        elif success:
            status = "PARTIAL"
        else:
            status = "FAILED"
        return BatchResult(
            status=status,
            total_rows=total,
            success_count=success,
            failure_count=len(errors),
            errors=errors,
        )

    def _upsert_tuition(self, student_no, term, amount, currency) -> AddTuitionResult:
        """Creates the tuition, or updates it if the student already has one for that term."""
        amount = parse_money(amount)
        if amount <= 0:
            raise InvalidInputError("amount must be greater than 0")
        currency = (currency or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise InvalidInputError("currency must be a 3 letter code like USD")

        student = self._get_student(student_no)
        if not term or self.terms.get(term) is None:
            raise NotFoundError(f"term {term} not found")

        tuition = self.tuitions.get(student.id, term, lock=True)
        if tuition is None:
            self.tuitions.add(
                Tuition(
                    student_id=student.id,
                    term_code=term,
                    amount=amount,
                    paid_amount=Decimal("0.00"),
                    currency=currency,
                )
            )
            status = "CREATED"
        else:
            if amount < tuition.paid_amount:
                raise ConflictError(
                    f"new amount {amount} is lower than the already paid amount {tuition.paid_amount}"
                )
            if tuition.paid_amount > 0 and currency != tuition.currency:
                raise ConflictError("currency can not be changed after a payment was made")
            tuition.amount = amount
            tuition.currency = currency
            self.db.flush()
            status = "UPDATED"

        return AddTuitionResult(
            status=status, student_no=student.student_no, term=term, amount=amount, currency=currency
        )

    # ---------- unpaid tuition status ----------

    def get_unpaid_tuitions(self, term, page=1, page_size=20):
        if page < 1:
            raise InvalidInputError("page must be 1 or more")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise InvalidInputError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        if not term or self.terms.get(term) is None:
            raise NotFoundError(f"term {term} not found")

        rows, total = self.tuitions.list_unpaid(term, (page - 1) * page_size, page_size)
        items = [
            UnpaidTuitionItem(
                student_no=t.student.student_no,
                full_name=t.student.full_name,
                tuition_total=t.amount,
                paid_amount=t.paid_amount,
                balance=t.balance,
                currency=t.currency,
            )
            for t in rows
        ]
        return UnpaidTuitionPage(
            term=term,
            page=page,
            page_size=page_size,
            total_items=total,
            total_pages=math.ceil(total / page_size),
            items=items,
        )

    # ---------- helpers ----------

    def _get_student(self, student_no) -> Student:
        student_no = (student_no or "").strip()
        if not student_no:
            raise InvalidInputError("student number is required")
        student = self.students.get_by_no(student_no)
        if student is None:
            raise NotFoundError(f"student {student_no} not found")
        return student
