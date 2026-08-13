"""HTTP client for the Amco+ API: authentication, token lifecycle, requests."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import httpx

from .exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)

if TYPE_CHECKING:
    from .resources.installation import Installation

__all__ = ["DEFAULT_API_URL", "AmcoClient", "raise_for_error"]

DEFAULT_API_URL = "https://amcoplusapi.farmadosis.com/api"
"""Cloud deployment. On-premise installations pass their own `base_url`."""


def raise_for_error(response: httpx.Response) -> None:
    """Inspect a response and raise the matching Amco+ exception.

    This is the only place in the library that turns an HTTP response into an
    exception. When a new Amco+ `error_code` is identified, add a branch here
    rather than checking codes at the call site.

    Amco+'s own `error_code` is more reliable than the HTTP status, so it is
    checked first.

    Raises:
        AuthenticationError: `error_code` 9001, invalid credentials.
        NotFoundError: HTTP 404.
        ValidationError: HTTP 422.
        APIError: Anything else, including non-JSON bodies from a proxy.
    """
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
    """Client for the Amco+ API. Handles login and token lifecycle.

    You do not need to call `login()`: the first request does it, and every
    later request re-logs in once the token has expired.

    The client reads no configuration of its own — no environment variables, no
    `.env`. Pass credentials in. That is deliberate, because Amco+ is deployed
    on-premise in hospitals and prisons where the URL is not the cloud one.

    Args:
        login: Username, usually an email address.
        password: Password.
        base_url: API root, without a trailing slash. Defaults to the cloud
            deployment; on-premise installations have their own.
        code: Two-factor code. Usually `None`.
        timeout: Seconds before a request gives up. The default is generous
            because `itemsPerPage=-1` responses are large and slow; httpx's own
            5s default is far too low here.
        verify_ssl: Set `False` only for on-premise servers with a self-signed
            certificate. httpx will warn on every request, which is intended —
            do not silence it.

    Attributes:
        access_token: Bearer token, or `None` before the first login.
        expires_at: Token expiry, timezone-aware and in UTC.

    Example:
        ```python
        client = AmcoClient(login="user@example.com", password="...")
        for installation in client.installations():
            print(installation["id"])

        center = client.installation(65).center(417)
        patients = center.patients.list(is_active=True)
        ```
    """

    def __init__(
        self,
        login: str,
        password: str,
        *,
        base_url: str = DEFAULT_API_URL,
        code: str | None = None,
        timeout: float = 120.0,
        verify_ssl: bool = True,
    ) -> None:
        self.login_name = login
        self.password = password
        self.base_url = base_url.rstrip("/")
        self.code = code
        self.timeout = timeout
        self.access_token: str | None = None
        self.expires_at: datetime | None = None
        self.verify_ssl = verify_ssl

    def login(self) -> dict[str, Any]:
        """Authenticate against Amco+ and store the token on the instance.

        Called automatically by `request()`; call it directly only if you want
        the login payload, which carries the user's roles and permissions.

        Returns:
            The full login response. It contains `access_token` — never log or
            print it.

        Raises:
            AuthenticationError: Credentials rejected.
        """
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

    def is_token_valid(self) -> bool:
        """Whether a token is stored and has not expired.

        Expiry is read from the login response rather than assumed, because
        token lifetime varies per installation. The comparison is against UTC;
        a naive `datetime.now()` would be local time and silently wrong.
        """
        if self.access_token is None or self.expires_at is None:
            return False
        return self.expires_at > datetime.now(timezone.utc)

    def request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        """Make an authenticated request, logging in first if needed.

        Args:
            method: HTTP method. Amco+ writes with `POST` to paths like
                `{resource}/create`, so this is almost always `"GET"` or
                `"POST"`.
            endpoint: Path starting with `/`, relative to `base_url`.
            **kwargs: Passed through to httpx — typically `params=` or `json=`.

        Returns:
            The decoded JSON body. Usually a `dict`, but a few endpoints
            return a bare `list` — `/installations/{id}/centers` is one — so
            this is deliberately untyped. Endpoints that return a file are not
            supported yet.
        """
        if not self.is_token_valid():
            self.login()

        headers = {"Authorization": f"Bearer {self.access_token}"}

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

    def get(self, endpoint: str, **kwargs: Any) -> Any:
        """Authenticated GET. See `request()`."""
        return self.request("GET", endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs: Any) -> Any:
        """Authenticated POST. See `request()`."""
        return self.request("POST", endpoint, **kwargs)

    def installation(self, installation_id: int) -> "Installation":
        """Return an `Installation` scope for the given id.

        No request is made; the scope is built locally. Use
        `installations()` first if you do not know the id.
        """
        from .resources.installation import Installation

        return Installation(self, installation_id)

    def installations(self, **filters: Any) -> list[dict[str, Any]]:
        """List all installations visible to the current user.

        `GET /installations/search`

        Args:
            **filters: Query parameters, e.g. `is_active=True`.
        """
        params: dict[str, Any] = {"itemsPerPage": -1}
        params.update(filters)
        return self.get("/installations/search", params=params)["items"]

    def __repr__(self) -> str:
        state = "authenticated" if self.is_token_valid() else "not authenticated"
        return f"AmcoClient(base_url={self.base_url!r}, {state})"
