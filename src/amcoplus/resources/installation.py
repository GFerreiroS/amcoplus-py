from .base import Resource


class Cassettes(Resource):
    path = "cassettes"


class Machines(Resource):
    path = "machines"


class Installation:
    """A pharmacy installation. Pharmacy-level resources hang off here."""

    def __init__(self, client, installation_id: int):
        self._client = client
        self.id = installation_id
        self._base_path = f"/installations/{installation_id}"

        self.cassettes = Cassettes(client, self._base_path)
        self.machines = Machines(client, self._base_path)

    def center(self, center_id: int):
        """Return a Center scoped to this installation."""
        from .center import Center
        return Center(self._client, self._base_path, center_id)
