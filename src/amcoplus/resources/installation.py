"""Installation (pharmacy) scope and its pharmacy-level resources."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .base import Resource

if TYPE_CHECKING:
    from ..client import AmcoClient
    from .center import Center

__all__ = [
    "Cassettes",
    "Installation",
    "Layouts",
    "Machines",
    "Trays",
    "Warehouses",
]


class Cassettes(Resource):
    """Cassettes of the installation — `/installations/{id}/cassettes/search`.

    Filters:
        is_active (bool): Only active cassettes.
        query (str): Free-text search.
        find_deactived_cassette_medicines (int): `0` or `1`. Note the API's
            own spelling of "deactived".
    """

    path = "cassettes"


class Machines(Resource):
    """Blistering machines — `/installations/{id}/machines`."""

    path = "machines"


class Layouts(Resource):
    """Bag layouts — `/installations/{id}/layouts`.

    Endpoint name is a first-pass guess and has not been confirmed against the
    API yet.
    """

    path = "layouts"


class Trays(Resource):
    """Trays — `/installations/{id}/trays`."""

    path = "trays"


class Warehouses(Resource):
    """Warehouses — `/installations/{id}/warehouses`.

    Endpoint name is a first-pass guess and has not been confirmed against the
    API yet.
    """

    path = "warehouses"


class Installation:
    """A pharmacy installation. Pharmacy-level resources hang off here.

    Get one from the client rather than building it directly:

        installation = client.installation(65)

    Attributes:
        id: The installation id, as it appears in the URL.
        cassettes: See `Cassettes`.
        machines: See `Machines`.
        layouts: See `Layouts`.
        trays: See `Trays`.
        warehouses: See `Warehouses`.

    Example:
        ```python
        installation = client.installation(65)
        print(installation.details()["name"])
        for cassette in installation.cassettes.list(is_active=True):
            ...
        ```
    """

    def __init__(self, client: "AmcoClient", installation_id: int) -> None:
        self._client = client
        self.id = installation_id
        self._base_path = f"/installations/{installation_id}"

        self.cassettes = Cassettes(client, self._base_path)
        self.machines = Machines(client, self._base_path)
        self.layouts = Layouts(client, self._base_path)
        self.trays = Trays(client, self._base_path)
        self.warehouses = Warehouses(client, self._base_path)

    def details(self) -> dict[str, Any]:
        """Fetch this installation's own record — `GET /installations/{id}`."""
        return self._client.get(self._base_path)

    def center(self, center_id: int) -> "Center":
        """Return a `Center` scoped to this installation.

        No request is made; the scope is built locally. An invalid id only
        fails when you actually call something on it.
        """
        from .center import Center

        return Center(self._client, self._base_path, center_id)

    def __repr__(self) -> str:
        return f"Installation(id={self.id})"
