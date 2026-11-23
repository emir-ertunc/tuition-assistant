"""Business rule errors.

The service layer raises these, the api layer turns them into http responses.
`code` is sent to the client so it can tell the errors apart.
"""


class TuitionError(Exception):
    code = "TUITION_ERROR"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInputError(TuitionError):
    code = "INVALID_INPUT"


class NotFoundError(TuitionError):
    code = "NOT_FOUND"


class ConflictError(TuitionError):
    code = "CONFLICT"


class DuplicateTransactionError(TuitionError):
    code = "DUPLICATE_TRANSACTION"


class AmountExceedsBalanceError(TuitionError):
    code = "AMOUNT_EXCEEDS_BALANCE"


class QueryLimitExceededError(TuitionError):
    code = "QUERY_LIMIT_EXCEEDED"


class AuthenticationError(TuitionError):
    # no token, wrong token or wrong password
    code = "UNAUTHORIZED"


class ForbiddenError(TuitionError):
    # valid token but not allowed (wrong role, or another student's data)
    code = "FORBIDDEN"
