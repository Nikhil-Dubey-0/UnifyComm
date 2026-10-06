from pydantic import BaseModel, ConfigDict


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class Page[T](BaseModel):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    items: list[T]
    next_cursor: str | None = None


class JobAccepted(BaseModel):
    job_id: int


ERROR_RESPONSES: dict[int | str, dict] = {
    status: {"model": ErrorResponse} for status in (401, 403, 404, 409, 422)
}
