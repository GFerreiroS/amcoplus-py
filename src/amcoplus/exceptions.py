from __future__ import annotations


class AmcoError(Exception):
    """App exception"""
    def __init__(self,
        *,
        error_code: int | None = None,
        error_message: str = "Unknown error",
        details: str | None = None,
        log_correlation_id: str | None = None
    ) -> None:
        self.error_code = error_code
        self.error_message = error_message
        self.details = details
        self.log_correlation_id = log_correlation_id
        # super().__init__(f"Error code: {error_code}\nError message: {error_message}\nDetails: {details}\nLog correlation: {log_correlation_id}")

    @classmethod
    def from_response(cls, data: dict):
        """Build the exception from the API's JSON error envelope."""
        return cls(
            error_code=data.get("error_code"),
            error_message=data.get("error_message", "Unknown error"),
            details=data.get("details"),
            log_correlation_id=data.get("log_correlation_id")
        )

class AuthenticationError(AmcoError):
    """Login rejected: invalid credentials or blocked account (error_code 9001)."""

class NotFoundError(AmcoError):
    """When a resource doesnt exist"""

class ValidationError(AmcoError):
    """The API rejected the request payload."""

class APIError(AmcoError):
    """Unclassified API error — used until we identify the specific error_code."""
