"""Domain exceptions. One handler in app.main maps them to {"error": {"code", "message"}}."""


class DomainError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class NotFound(DomainError):
    status_code = 404
    code = "not_found"


class Unauthorized(DomainError):
    status_code = 401
    code = "unauthorized"


class Forbidden(DomainError):
    status_code = 403
    code = "forbidden"


class Conflict(DomainError):
    status_code = 409
    code = "conflict"


class Unprocessable(DomainError):
    status_code = 422
    code = "unprocessable"


class LLMUnavailable(DomainError):
    status_code = 503
    code = "llm_unavailable"
