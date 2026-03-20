"""Common Pydantic schemas shared across multiple API domains."""

from pydantic import BaseModel


class ErrorResponse(BaseModel):
    """Standard error response body returned for API errors.

    Fields:
        detail: Human-readable description of the error.
        error_code: Optional machine-readable code for programmatic handling.
        current_version: The character's current version number, included in
            409/422 version-conflict responses.
    """

    detail: str
    error_code: str | None = None
    current_version: int | None = None
