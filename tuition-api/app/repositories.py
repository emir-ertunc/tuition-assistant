"""Data access layer. Only queries here, no business rules.

Repositories only flush, the service decides when to commit.
"""

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.models import Payment, Student, Term, Tuition, TuitionQueryLog, User


class UserRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_username(self, username: str) -> User | None:
        query = select(User).options(joinedload(User.student)).where(User.username == username)
        return self.db.scalar(query)


class StudentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_no(self, student_no: str) -> Student | None:
        return self.db.scalar(select(Student).where(Student.student_no == student_no))


class TermRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, code: str) -> Term | None:
        return self.db.get(Term, code)


class TuitionRepository:
    def __init__(self, db: Session):
        self.db = db

    def list_for_student(self, student_id: int) -> list[Tuition]:
        query = (
            select(Tuition)
            .join(Term)
            .options(joinedload(Tuition.term))
            .where(Tuition.student_id == student_id)
            .order_by(Term.start_date)
        )
        return list(self.db.scalars(query))

    def get(self, student_id: int, term_code: str, lock: bool = False) -> Tuition | None:
        query = select(Tuition).where(
            Tuition.student_id == student_id, Tuition.term_code == term_code
        )
        if lock:
            # row lock so two payments for the same tuition can't run at the same time
            query = query.with_for_update()
        return self.db.scalar(query)

    def add(self, tuition: Tuition) -> None:
        self.db.add(tuition)
        self.db.flush()

    def list_unpaid(self, term_code: str, offset: int, limit: int) -> tuple[list[Tuition], int]:
        condition = (Tuition.term_code == term_code) & (Tuition.paid_amount < Tuition.amount)

        total = self.db.scalar(select(func.count()).select_from(Tuition).where(condition))
        rows = self.db.scalars(
            select(Tuition)
            .options(joinedload(Tuition.student))
            .where(condition)
            .order_by(Tuition.id)
            .offset(offset)
            .limit(limit)
        )
        return list(rows), total


class PaymentRepository:
    def __init__(self, db: Session):
        self.db = db

    def exists(self, transaction_id: str) -> bool:
        query = select(Payment.id).where(Payment.transaction_id == transaction_id)
        return self.db.scalar(query) is not None

    def add(self, payment: Payment) -> None:
        self.db.add(payment)
        self.db.flush()


class QueryLogRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, student_id: int, day: date) -> TuitionQueryLog | None:
        query = (
            select(TuitionQueryLog)
            .where(TuitionQueryLog.student_id == student_id, TuitionQueryLog.query_date == day)
            .with_for_update()
        )
        return self.db.scalar(query)

    def add(self, log: TuitionQueryLog) -> None:
        self.db.add(log)
        self.db.flush()
