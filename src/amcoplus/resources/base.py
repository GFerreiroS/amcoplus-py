"""Base class shared by all Amco+ resource endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..client import AmcoClient

__all__ = [
    "BareListResource",
    "DirectResource",
    "Resource",
    "WritableBareListResource",
]

JSONDict = dict[str, Any]


class BareListResource:
    """A collection that returns a bare JSON list, not a `/search` envelope.

    A few Amco+ collections have no `/search` and no `{"items": ...}` wrapper:
    the GET on the collection path returns the list directly. A center's list of
    integrations and an installation's machines are like this, the same way
    `/installations/{i}/centers` is. `Resource` does not fit them — asking for
    `{path}/search` would parse `search` as an id — so they use this instead.

    Subclasses set `path` and are registered on the owning scope, reached as
    `center.integrations` or `installation.machines`. `list()` is the
    collection GET; `get(id)` is one item at `{url}/{id}`.
    """

    path: str = ""
    """Endpoint segment appended to the parent scope."""

    def __init__(self, client: "AmcoClient", base_path: str) -> None:
        self._client = client
        self._base_path = base_path

    @property
    def url(self) -> str:
        """Path of this collection, without the API base URL."""
        return f"{self._base_path}/{self.path}"

    def list(self, **filters: Any) -> list[JSONDict]:
        """Return the collection as a plain list.

        Args:
            **filters: Optional query parameters. Which ones an endpoint accepts
                depends on the resource — see its docstring. Amco+ silently
                ignores unknown ones.
        """
        return self._client.get(self.url, params=filters or None)

    def get(self, resource_id: int) -> JSONDict:
        """Fetch a single item by id, from `{url}/{resource_id}`."""
        return self._client.get(f"{self.url}/{resource_id}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url={self.url!r})"


class WritableBareListResource(BareListResource):
    """A `BareListResource` that also writes rows.

    The API's real write convention — verified on integrations, doctors, modules
    and submodules — is **`POST {url}/create`**, **`PUT {url}/{id}/update`** and
    **`DELETE {url}/{id}/delete`**, not the all-POST scheme the older notes
    assumed. `create` and `update` take a free body; which keys a resource wants
    is documented on the subclass (and only enforced by the API). Not every
    resource offers `delete` (doctors and modules do not) — subclasses that do
    inherit `delete`; the others simply do not expose it.
    """

    def create(self, **fields: Any) -> Any:
        """Create a row — `POST {url}/create` with `fields` as the body."""
        return self._client.post(f"{self.url}/create", json=fields)

    def update(self, resource_id: int, **fields: Any) -> Any:
        """Update a row — `PUT {url}/{resource_id}/update`.

        A PUT (POST gives 405). Pass the fields to change.
        """
        return self._client.request(
            "PUT", f"{self.url}/{resource_id}/update", json=fields
        )

    def _delete(self, resource_id: int) -> Any:
        """Delete a row — `DELETE {url}/{resource_id}/delete`.

        Exposed as `delete` only by subclasses whose endpoint supports it.
        """
        return self._client.request("DELETE", f"{self.url}/{resource_id}/delete")


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

    default_items_per_page: int | None = -1
    """Page size used when `all_items=True`.

    `-1` means "everything in one response", which is what we normally want and
    why the client has a generous timeout. Override it where that would be a
    bad idea — paper rolls and support access logs have ~200k rows.

    `None` means "send no page-size parameter at all". A few endpoints reject
    any pagination param with a 500 and only answer when the query string is
    empty — the integration-provider searches are like this.
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

    def _search_params(self, all_items: bool, filters: JSONDict) -> JSONDict:
        """Build this endpoint's pagination and filter query."""
        params: JSONDict = {}
        if self.default_items_per_page is not None:
            params[self.items_per_page_param] = (
                self.default_items_per_page if all_items else 15
            )
        params.update(filters)
        return params

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Same as `list()` but returns the full envelope.

        Use this when you need `maxResults`, e.g. to count rows without
        holding them all.

        Returns:
            `{"items": [...], "maxResults": N}`.
        """
        params = self._search_params(all_items, filters)
        return self._client.get(f"{self.url}/search", params=params or None)

    def get(self, resource_id: int) -> JSONDict:
        """Fetch a single item by id, from `{url}/{resource_id}`.

        Missing rows do not consistently produce an HTTP 404 in Amco+; some
        endpoints instead fail with a generic API error. Callers should catch
        `AmcoError` rather than relying on `NotFoundError` here.
        """
        return self._client.get(f"{self.url}/{resource_id}")

    def __repr__(self) -> str:
        return f"{type(self).__name__}(url={self.url!r})"


class DirectResource(Resource):
    """A paginated collection whose GET is its collection path directly.

    Its response still has the usual `{"items": [...], "maxResults": N}`
    envelope, but the endpoint is `{url}` rather than `{url}/search`. Patient
    sales and holiday periods use this less common shape.
    """

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Return the full pagination envelope from `GET {url}`."""
        params = self._search_params(all_items, filters)
        return self._client.get(self.url, params=params or None)
