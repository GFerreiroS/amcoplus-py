"""Base class shared by all Amco+ resource endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AmcoClient

__all__ = ["Resource"]

JSONDict = dict[str, Any]


class Resource:
    """Generic list/get behaviour for an Amco+ resource collection.

    Subclasses set `path` and are registered as an attribute on the scope that
    owns them, so a caller reaches them as `installation.cassettes` or
    `center.patients`. The full URL is the owning scope's path plus `path`:

        Cassettes(client, "/installations/5").url  ->  "/installations/5/cassettes"

    Listing goes through `{url}/search`, which returns
    `{"items": [...], "maxResults": N}`.

    Class attributes exist because the API is not uniform — see
    `default_items_per_page` and `items_per_page_param` below. Check the
    resource's own docstring for the filters it accepts; passing an unknown
    filter is silently ignored by the API rather than rejected.
    """

    path: str = ""
    """Endpoint segment appended to the parent scope, e.g. `"cassettes"`."""

    items_per_page_param: str = "itemsPerPage"
    """Name of the page-size parameter.

    Most endpoints use camelCase `itemsPerPage`, but a few want snake_case
    `items_per_page` (paper rolls, translations, support access logs).
    """

    default_items_per_page: int = -1
    """Page size used when `all_items=True`.

    `-1` means "everything in one response", which is what we normally want and
    why the client has a generous timeout. Override it where that would be a
    bad idea — paper rolls and support access logs have ~200k rows.
    """

    def __init__(self, client: "AmcoClient", base_path: str) -> None:
        self._client = client
        self._base_path = base_path

    @property
    def url(self) -> str:
        """Path of this collection, without the API base URL."""
        return f"{self._base_path}/{self.path}"

    def list(self, *, all_items: bool = True, **filters: Any) -> list[JSONDict]:
        """Return the items, dropping the pagination envelope.

        Args:
            all_items: Ask for every row in one response. Set `False` to get a
                single page of 15 and pass `page=N` to walk them.
            **filters: Query parameters, e.g. `is_active=True`. Which ones are
                accepted depends on the resource — see its docstring.

        Returns:
            The `items` list. Each item is the raw JSON object from the API.

        Example:
            ```python
            active = installation.cassettes.list(is_active=True)
            print(len(active))
            ```
        """
        return self.search(all_items=all_items, **filters)["items"]

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Same as `list()` but returns the full envelope.

        Use this when you need `maxResults`, e.g. to count rows without
        holding them all.

        Returns:
            `{"items": [...], "maxResults": N}`.
        """
        params: JSONDict = {
            self.items_per_page_param: self.default_items_per_page if all_items else 15
        }
        params.update(filters)
        return self._client.get(f"{self.url}/search", params=params)

    def get(self, resource_id: int) -> JSONDict:
        """Fetch a single item by id, from `{url}/{resource_id}`.

        Raises:
            NotFoundError: The id does not exist.
        """
        return self._client.get(f"{self.url}/{resource_id}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url={self.url!r})"
