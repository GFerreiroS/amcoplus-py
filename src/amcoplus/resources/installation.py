"""Installation (pharmacy) scope and its pharmacy-level resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Resource

if TYPE_CHECKING:
    from ..client import AmcoClient
    from .center import Center


class Cassettes(Resource):
    path = "cassettes"


class Machines(Resource):
    path = "machines"


class Layouts(Resource):
    path = "layouts"


class Trays(Resource):
    path = "trays"


class Warehouses(Resource):
    path = "warehouses"


class Installation:
    """A pharmacy installation. Pharmacy-level resources hang off here."""

    def __init__(self, client: "AmcoClient", installation_id: int):
        self._client = client
        self.id = installation_id
        self._base_path = f"/installations/{installation_id}"

        self.cassettes = Cassettes(client, self._base_path)
        self.machines = Machines(client, self._base_path)
        self.layouts = Layouts(client, self._base_path)
        self.trays = Trays(client, self._base_path)
        self.warehouses = Warehouses(client, self._base_path)

    def center(self, center_id: int) -> "Center":
        """Return a Center scoped to this installation."""
        from .center import Center
        return Center(self._client, self._base_path, center_id)

    def __repr__(self) -> str:
        return f"Installation(id={self.id})"
