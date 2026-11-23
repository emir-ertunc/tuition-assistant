from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# NUMERIC(12,2) for all money columns, no floats
Money = Numeric(12, 2)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_no: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tuitions: Mapped[list["Tuition"]] = relationship(back_populates="student")


class Term(Base):
    __tablename__ = "terms"

    code: Mapped[str] = mapped_column(String(20), primary_key=True)  # e.g. 2026-FALL
    name: Mapped[str] = mapped_column(String(50))
    start_date: Mapped[date] = mapped_column(Date)
    payment_deadline: Mapped[date] = mapped_column(Date)


class Tuition(Base):
    __tablename__ = "tuitions"
    __table_args__ = (
        UniqueConstraint("student_id", "term_code", name="uq_tuition_student_term"),
        CheckConstraint("amount >= 0", name="ck_tuition_amount"),
        CheckConstraint("paid_amount >= 0 AND paid_amount <= amount", name="ck_tuition_paid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    term_code: Mapped[str] = mapped_column(ForeignKey("terms.code"), index=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    paid_amount: Mapped[Decimal] = mapped_column(Money, default=Decimal("0.00"))
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    student: Mapped[Student] = relationship(back_populates="tuitions")
    term: Mapped[Term] = relationship()
    payments: Mapped[list["Payment"]] = relationship(back_populates="tuition")

    @property
    def balance(self) -> Decimal:
        return self.amount - self.paid_amount


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (CheckConstraint("amount > 0", name="ck_payment_amount"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tuition_id: Mapped[int] = mapped_column(ForeignKey("tuitions.id"), index=True)
    # unique so the same payment can not be saved twice
    transaction_id: Mapped[str] = mapped_column(String(64), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    status: Mapped[str] = mapped_column(String(20), default="COMPLETED")
    channel: Mapped[str] = mapped_column(String(20))  # BANK or AGENT
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tuition: Mapped[Tuition] = relationship(back_populates="payments")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('STUDENT', 'BANK', 'ADMIN')", name="ck_user_role"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20))
    # only filled for STUDENT users
    student_id: Mapped[int | None] = mapped_column(ForeignKey("students.id"))

    student: Mapped[Student | None] = relationship()


class TuitionQueryLog(Base):
    """Daily counter for the mobile query tuition endpoint (3 per student per day)."""

    __tablename__ = "tuition_query_logs"
    __table_args__ = (
        UniqueConstraint("student_id", "query_date", name="uq_query_student_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"))
    query_date: Mapped[date] = mapped_column(Date)
    query_count: Mapped[int] = mapped_column(default=0)
