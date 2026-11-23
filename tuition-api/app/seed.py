"""Creates the tables and fills them with test data.

usage:
    python -m app.seed           -> create tables + seed (skips if data already exists)
    python -m app.seed --reset   -> drop all tables first, then create + seed
"""

import sys
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models import Payment, Student, Term, Tuition, User
from app.security import hash_password

# deadlines are taken from the policy document (section 2.1 and 2.2)
TERMS = [
    ("2026-FALL", "Fall 2026", date(2026, 9, 14), date(2026, 9, 30)),
    ("2027-SPRING", "Spring 2027", date(2027, 2, 1), date(2027, 2, 15)),
]

STUDENTS = [
    ("20210001", "Ayse Yilmaz", "ayse.yilmaz@student.example.edu"),
    ("20210002", "Mehmet Demir", "mehmet.demir@student.example.edu"),
    ("20210003", "Zeynep Kaya", "zeynep.kaya@student.example.edu"),
    ("20210004", "Can Ozturk", "can.ozturk@student.example.edu"),
]

# student_no, term, amount, paid
TUITIONS = [
    ("20210001", "2026-FALL", "3000.00", "0.00"),     # same as the example in the assignment
    ("20210001", "2027-SPRING", "3000.00", "0.00"),
    ("20210002", "2026-FALL", "2500.00", "2500.00"),  # fully paid
    ("20210003", "2026-FALL", "4000.00", "1000.00"),  # partially paid
    ("20210004", "2026-FALL", "250.00", "0.00"),      # below the $300 installment limit
]

# payments that explain the paid amounts above
PAYMENTS = [
    ("20210002", "2026-FALL", "SEED-TX-0001", "2500.00", "BANK"),
    ("20210003", "2026-FALL", "SEED-TX-0002", "1000.00", "BANK"),
]


# test accounts for the demo (only test passwords, nothing real)
# username, password, role, student_no
USERS = [
    ("admin", "admin123", "ADMIN", None),
    ("bank", "bank123", "BANK", None),
    ("20210001", "student123", "STUDENT", "20210001"),
    ("20210002", "student123", "STUDENT", "20210002"),
    ("20210003", "student123", "STUDENT", "20210003"),
    ("20210004", "student123", "STUDENT", "20210004"),
]


def seed(db):
    if db.scalar(select(Student).limit(1)) is not None:
        print("tuition data already exists, skipping it (use --reset to start over)")
        return

    for code, name, start, deadline in TERMS:
        db.add(Term(code=code, name=name, start_date=start, payment_deadline=deadline))

    students = {}
    for no, name, email in STUDENTS:
        s = Student(student_no=no, full_name=name, email=email)
        db.add(s)
        students[no] = s
    db.flush()  # so the students get their ids

    tuitions = {}
    for no, term, amount, paid in TUITIONS:
        t = Tuition(
            student_id=students[no].id,
            term_code=term,
            amount=Decimal(amount),
            paid_amount=Decimal(paid),
            currency="USD",
        )
        db.add(t)
        tuitions[(no, term)] = t
    db.flush()

    for no, term, tx_id, amount, channel in PAYMENTS:
        db.add(
            Payment(
                tuition_id=tuitions[(no, term)].id,
                transaction_id=tx_id,
                amount=Decimal(amount),
                channel=channel,
            )
        )

    db.commit()
    print(f"seeded {len(TERMS)} terms, {len(STUDENTS)} students, "
          f"{len(TUITIONS)} tuitions, {len(PAYMENTS)} payments")


def seed_users(db):
    if db.scalar(select(User).limit(1)) is not None:
        print("users already exist, skipping them")
        return

    for username, password, role, student_no in USERS:
        student_id = None
        if student_no:
            student_id = db.scalar(select(Student.id).where(Student.student_no == student_no))
        db.add(
            User(
                username=username,
                password_hash=hash_password(password),
                role=role,
                student_id=student_id,
            )
        )
    db.commit()
    print(f"seeded {len(USERS)} users")


def main():
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)
        print("tables dropped")

    Base.metadata.create_all(engine)
    print("tables created")

    with SessionLocal() as db:
        seed(db)
        seed_users(db)


if __name__ == "__main__":
    main()
