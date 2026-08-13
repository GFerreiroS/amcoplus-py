from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .exceptions import (
    AmcoError,
    APIError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)

DEFAULT_API_URL = "https://amcoplusapi.farmadosis.com/api"

def raise_for_error(response: httpx.Response) -> None:
    """Inspect a response and raise the matching Amco+ exception."""
    if response.status_code < 400:
        return  # success, nothing to do

    try:
        data = response.json()
    except ValueError:
        # The API didn't return JSON (proxy error, HTML page, empty body...)
        raise APIError(
            error_message=f"Non-JSON error response (HTTP {response.status_code})"
        )

    error_code = data.get("error_code")

    if error_code == 9001:
        raise AuthenticationError.from_response(data)
    if response.status_code == 404:
        raise NotFoundError.from_response(data)
    if response.status_code == 422:
        raise ValidationError.from_response(data)

    raise APIError.from_response(data)

class AmcoClient:
    """Client for the Amco+ API. Handles login and token lifecycle."""

    def __init__(
            self,
            login: str,
            password: str,
            *,
            base_url: str = DEFAULT_API_URL,
            code: str | None = None,
            timeout: float = 120.0,
            verify_ssl: bool = True,
        ):
            self.login_name = login
            self.password = password
            self.base_url = base_url.rstrip("/")
            self.code = code
            self.timeout = timeout
            self.access_token: str | None = None
            self.expires_at: datetime | None = None
            self.verify_ssl = verify_ssl

    def login(self) -> dict:
        """Authenticate against Amco+ and store the token in the instance."""
        login_dict = {
            "login": self.login_name,
            "password": self.password,
            "code": self.code,
        }

        response = httpx.post(
            f"{self.base_url}/login",
            json=login_dict,
            verify=self.verify_ssl,
            timeout=self.timeout,
        )
        raise_for_error(response)
        data = response.json()

        self.access_token = data["access_token"]
        self.expires_at = datetime.fromisoformat(data["session_expires_at_8601"])

        return data

    def is_token_valid(self)-> bool:
        if self.access_token is None or self.expires_at is None:
                    return False
        return self.expires_at > datetime.now(timezone.utc)

    def request(self, method: str, endpoint: str, **kwargs) -> dict:
        """Make an authenticated request against the Amco+ API."""
        if not self.is_token_valid():
            self.login()

        headers = {
            "Authorization": f"Bearer {self.access_token}"
        }

        response = httpx.request(
            method,
            f"{self.base_url}{endpoint}",
            headers=headers,
            verify=self.verify_ssl,
            timeout=self.timeout,
            **kwargs,
        )
        raise_for_error(response)
        return response.json()

    def get(self, endpoint: str, **kwargs) -> dict:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> dict:
        return self.request("POST", endpoint, **kwargs)

    def installation(self, installation_id: int):
            """Return an Installation scope for the given id."""
            from .resources.installation import Installation
            return Installation(self, installation_id)

    def installations(self, **filters):
        """List all installations visible to the current user."""
        params = {"itemsPerPage": -1}
        params.update(filters)
        return self.get("/installations/search", params=params)["items"]
