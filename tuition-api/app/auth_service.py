from sqlalchemy.orm import Session

from app.exceptions import AuthenticationError
from app.repositories import UserRepository
from app.schemas import TokenResponse
from app.security import create_access_token, hash_password, verify_password

# used when the username does not exist, so a wrong username and a wrong password
# take about the same time (otherwise you could guess usernames from the response time)
_DUMMY_HASH = hash_password("dummy-password")


class AuthService:
    def __init__(self, db: Session):
        self.users = UserRepository(db)

    def login(self, username: str, password: str) -> TokenResponse:
        user = self.users.get_by_username((username or "").strip())
        if user is None:
            verify_password(password, _DUMMY_HASH)
            raise AuthenticationError("wrong username or password")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("wrong username or password")

        student_no = user.student.student_no if user.student else None
        token, expires_in = create_access_token(user.username, user.role, student_no)
        return TokenResponse(access_token=token, expires_in=expires_in, role=user.role)
