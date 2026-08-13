"""Typed exceptions for the Amco+ API.

Every failed request raises one of these. They are built from the API's JSON
error envelope, so `error_code` is Amco+'s own numeric code, not the HTTP
status — it is the more reliable of the two.

Catch `AmcoError` to catch everything.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "AmcoError",
    "APIError",
    "AuthenticationError",
    "NotFoundError",
    "ValidationError",
]


class AmcoError(Exception):
    """Base class for every Amco+ error.

    Attributes:
        error_code: Amco+'s numeric code, e.g. `9001` for invalid credentials.
            `None` when the response carried no envelope.
        error_message: The message as returned by the API, usually in Spanish.
        details: Extra context, typically field-level validation errors.
        log_correlation_id: Server-side trace id — quote it when reporting a
            problem to Farmadosis.

    Example:
        ```python
        try:
            client.installations()
        except AmcoError as exc:
            print(exc.error_code, exc.error_message)
        ```
    """

    def __init__(
        self,
        *,
        error_code: int | None = None,
        error_message: str = "Unknown error",
        details: str | None = None,
        log_correlation_id: str | None = None,
    ) -> None:
        self.error_code = error_code
        self.error_message = error_message
        self.details = details
        self.log_correlation_id = log_correlation_id
        super().__init__(self._describe())

    def _describe(self) -> str:
        """Build the message shown by `str(exc)` and by an uncaught traceback."""
        head = self.error_message
        if self.error_code is not None:
            head = f"[{self.error_code}] {head}"

        parts = [head]
        if self.details:
            parts.append(f"details: {self.details}")
        if self.log_correlation_id:
            parts.append(f"log_correlation_id: {self.log_correlation_id}")
        return " | ".join(parts)

    @classmethod
    def from_response(cls, data: dict[str, Any]) -> "AmcoError":
        """Build the exception from the API's JSON error envelope.

        Works on any subclass: `AuthenticationError.from_response(data)`
        returns an `AuthenticationError`.

        Args:
            data: The decoded error body, e.g.
                `{"error_code": 9001, "error_message": "Credenciales invalidas",
                  "details": None, "log_correlation_id": "d176..."}`
        """
        return cls(
            error_code=data.get("error_code"),
            error_message=data.get("error_message", "Unknown error"),
            details=data.get("details"),
            log_correlation_id=data.get("log_correlation_id"),
        )


class AuthenticationError(AmcoError):
    """Login rejected: invalid credentials or blocked account (error_code 9001)."""


class NotFoundError(AmcoError):
    """The requested resource does not exist (HTTP 404)."""


class ValidationError(AmcoError):
    """The API rejected the request payload (HTTP 422)."""


class APIError(AmcoError):
    """Unclassified API error — used until we identify the specific error_code."""
