"""Base class shared by all Amco+ resource endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AmcoClient


class Resource:
    """Generic list/get behaviour for an Amco+ resource collection."""

    path: str = ""  # subclasses override this, e.g. "cassettes"

    def __init__(self, client: "AmcoClient", base_path: str):
        self._client = client
        self._base_path = base_path

    @property
    def url(self) -> str:
        return f"{self._base_path}/{self.path}"

    def list(self, *, all_items: bool = True, **filters: Any) -> list[dict]:
        """Return the resource items. Extra kwargs are sent as query params."""
        params: dict[str, Any] = {"itemsPerPage": -1 if all_items else 15}
        params.update(filters)

        data = self._client.get(f"{self.url}/search", params=params)
        return data["items"]

    def get(self, resource_id: int) -> dict:
        """Fetch a single item by id."""
        return self._client.get(f"{self.url}/{resource_id}")
