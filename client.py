from __future__ import annotations

from datetime import datetime, timezone

import httpx

from exceptions import (
    AmcoError,
    APIError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)

API_URL = "https://amcoplusapi.farmadosis.com/api"

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

    def __init__(self, login: str, password: str, code: str | None = None, timeout: float = 120.0):
        self.login_name = login
        self.password = password
        self.code = code
        self.access_token: str | None = None
        self.expires_at: datetime | None = None
        self.timeout = timeout

    def login(self) -> dict:
        """Authenticate against Amco+ and store the token in the instance."""
        login_dict = {
            "login": self.login_name,
            "password": self.password,
            "code": self.code,
        }

        response = httpx.post(API_URL + "/login", json=login_dict)
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
            f"{API_URL}{endpoint}",
            headers=headers,
            timeout=self.timeout,
            **kwargs,
        )
        raise_for_error(response)
        return response.json()

    def get(self, endpoint: str, **kwargs) -> dict:
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs) -> dict:
        return self.request("POST", endpoint, **kwargs)

try:
    client = AmcoClient("gferreiro@farmadosis.com", "Farmadosis3")
    data = client.get("/installations/search", params={
        "page": 1,
        "itemsPerPage": 5,
        "is_active": True,
    })
    print(data)
except AuthenticationError as e:
    print("Login falló:", e.error_code, e.error_message)
