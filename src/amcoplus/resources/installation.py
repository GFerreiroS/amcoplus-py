"""Installation (pharmacy) scope and its pharmacy-level resources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .base import (
    BareListResource,
    DirectResource,
    Resource,
    WritableBareListResource,
)

if TYPE_CHECKING:
    from ..client import AmcoClient
    from .center import Center

__all__ = [
    "AdministrationRoutes",
    "Cassettes",
    "Centers",
    "HolidayReasons",
    "HospitalizationMotivations",
    "Installation",
    "InstallationMedicine",
    "InstallationMedicineFamily",
    "Layouts",
    "Machines",
    "MedicationProviders",
    "MedicineFamilies",
    "MedicineFamilyLevels",
    "Medicines",
    "MedicinesFamilies",
    "ProductionLayouts",
    "ProductionSorts",
    "Trays",
    "Warehouses",
]


def _validate_installation_record(
    details: Any,
    resource_id: int,
    installation_id: int,
    label: str,
) -> dict[str, Any]:
    """Reject an item endpoint that resolved outside its installation."""
    if not isinstance(resource_id, int) or isinstance(resource_id, bool):
        raise ValueError(f"{label} id must be an integer")
    if not isinstance(details, dict):
        raise TypeError(f"{label} response is not an object")
    returned_id = details.get("id")
    returned_installation_id = details.get("installation_id")
    if (
        not isinstance(returned_id, int)
        or isinstance(returned_id, bool)
        or returned_id != resource_id
        or not isinstance(returned_installation_id, int)
        or isinstance(returned_installation_id, bool)
        or returned_installation_id != installation_id
    ):
        raise ValueError(f"{label} does not belong to the scoped installation")
    return details


def _validate_center_record(
    details: Any,
    center_id: int,
    installation_id: int,
) -> dict[str, Any]:
    """Reject a center item resolved through another installation path."""
    return _validate_installation_record(
        details,
        center_id,
        installation_id,
        "center",
    )


def _installation_row(
    items: Any,
    resource_id: int,
    label: str,
) -> dict[str, Any]:
    """Locate one id in an installation-scoped bare collection."""
    if not isinstance(resource_id, int) or isinstance(resource_id, bool):
        raise ValueError(f"{label} id must be an integer")
    if not isinstance(items, list):
        raise TypeError(f"{label} collection response is not a list")
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if (
            isinstance(item_id, int)
            and not isinstance(item_id, bool)
            and item_id == resource_id
        ):
            return item
    raise ValueError(f"{label} does not belong to the scoped installation")


class Centers(WritableBareListResource):
    """Centers of an installation — `/installations/{i}/centers`.

    A **bare JSON list**, no `/search` and no envelope — asking for
    `/centers/search` fails (`search` is read as a center id). `get(id)` returns
    one center's detail; for the richer scope use `installation.center(id)`.

    `create(**fields)` adds a center (POST `/centers/create`). There is no
    center delete, and updates go through the scope: `installation.center(c).update()`.
    """

    path = "centers"

    @property
    def installation_id(self) -> int:
        return int(self._base_path.rsplit("/", 1)[-1])

    def _assert_belongs(self, center_id: int) -> None:
        _installation_row(self.list(), center_id, "center")

    def get(self, resource_id: int) -> dict[str, Any]:
        """Fetch detail only after proving list membership."""
        self._assert_belongs(resource_id)
        details = self._client.get(f"{self.url}/{resource_id}")
        return _validate_center_record(details, resource_id, self.installation_id)

    def create(self, **fields: Any) -> Any:
        """Create while rejecting a conflicting body installation id."""
        supplied = fields.get("installation_id")
        if supplied is not None and supplied != self.installation_id:
            raise ValueError("installation_id does not match the scoped resource")
        return super().create(**fields)

    def update(self, resource_id: int, **fields: Any) -> Any:
        """Update only a center present in this installation's list."""
        self._assert_belongs(resource_id)
        supplied = fields.get("installation_id")
        if supplied is not None and supplied != self.installation_id:
            raise ValueError("installation_id does not match the scoped resource")
        return super().update(resource_id, **fields)


class Cassettes(Resource):
    """Cassettes of the installation — `/installations/{id}/cassettes/search`.

    Filters:
        is_active (bool): Only active cassettes.
        query (str): Free-text search.
        find_deactived_cassette_medicines (int): `0` or `1`. Note the API's
            own spelling of "deactived".
    """

    path = "cassettes"


class Machines(BareListResource):
    """Blistering machines — `/installations/{id}/machines`.

    The collection returns a bare JSON list. It has no `/search` endpoint and
    takes no pagination parameters; this is the list used by the center form.
    """

    path = "machines"


class AdministrationRoutes(BareListResource):
    """Treatment administration routes — bare installation-level lookup."""

    path = "administration-routes"


class MedicationProviders(BareListResource):
    """Medication providers used by patient sale program codes.

    The observed collection route has a trailing slash. `list()` preserves it
    because some on-premise deployments do not redirect API requests.
    """

    path = "medication-providers"

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        """Return the bare provider list from `.../medication-providers/`."""
        return self._client.get(f"{self.url}/", params=filters or None)


class MedicinesFamilies(Resource):
    """Combined medicine/family collection used by older catalogue screens.

    `GET /installations/{i}/medicines-families/search`. Confirmed filters
    include `query`, `is_active`, `is_family`, `is_medicine` and `with_count`.
    This is distinct from the treatment editor's separate `medicines` and
    `medicine_families` collections below.
    """

    path = "medicines-families"


class Medicines(Resource):
    """Medicine autocomplete used by the treatment editor.

    `GET /installations/{i}/medicines/search`, with `query` and
    `with_count=False` in the SPA.
    """

    path = "medicines"


class MedicineFamilyLevels(Resource):
    """Medicine-family levels used to filter the treatment editor."""

    path = "medicine-family-levels"


class MedicineFamilies(Resource):
    """Medicine-family autocomplete used by the treatment editor.

    `GET /installations/{i}/medicine-families/search`, filtered by `query` and
    `medicine_family_level_id`.
    """

    path = "medicine-families"


class InstallationMedicine:
    """One installation medicine and its treatment-editor projections."""

    def __init__(
        self, client: "AmcoClient", installation_path: str, medicine_id: int
    ) -> None:
        self._client = client
        self.id = medicine_id
        self._installation_path = installation_path
        self._installation_id = int(installation_path.rsplit("/", 1)[-1])
        self._base_path = f"{installation_path}/medicines/{medicine_id}"

    def _checked_details(self) -> dict[str, Any]:
        details = self._client.get(self._base_path)
        return _validate_installation_record(
            details, self.id, self._installation_id, "medicine"
        )

    def _checked_center(self, center_id: int) -> None:
        details = self._client.get(
            f"{self._installation_path}/centers/{center_id}"
        )
        _validate_center_record(details, center_id, self._installation_id)

    def details(self) -> dict[str, Any]:
        """Fetch `GET /installations/{i}/medicines/{m}`."""
        return self._checked_details()

    def center_customization(self, center_id: int) -> dict[str, Any]:
        """Fetch the editor's center-customized medicine projection.

        `GET /installations/{i}/medicines/{m}/centers/{c}/customize`

        This route is not the inverse-path `center.medicine(m).customized()`;
        both exist in the current web application.
        """
        self._checked_details()
        self._checked_center(center_id)
        details = self._client.get(
            f"{self._base_path}/centers/{center_id}/customize"
        )
        return _validate_installation_record(
            details, self.id, self._installation_id, "medicine"
        )

    def medicines_in_family(self) -> list[dict[str, Any]]:
        """Return medicines in this medicine's family."""
        self._checked_details()
        return self._client.get(f"{self._base_path}/medicines-in-family")

    def __repr__(self) -> str:
        return f"InstallationMedicine(id={self.id})"


class InstallationMedicineFamily:
    """One installation medicine family and its center projection."""

    def __init__(
        self, client: "AmcoClient", installation_path: str, family_id: int
    ) -> None:
        self._client = client
        self.id = family_id
        self._installation_path = installation_path
        self._installation_id = int(installation_path.rsplit("/", 1)[-1])
        self._base_path = f"{installation_path}/medicine-families/{family_id}"

    def _checked_details(self) -> dict[str, Any]:
        details = self._client.get(self._base_path)
        return _validate_installation_record(
            details, self.id, self._installation_id, "medicine family"
        )

    def _checked_center(self, center_id: int) -> None:
        details = self._client.get(
            f"{self._installation_path}/centers/{center_id}"
        )
        _validate_center_record(details, center_id, self._installation_id)

    def details(self) -> dict[str, Any]:
        """Fetch `GET /installations/{i}/medicine-families/{f}`."""
        return self._checked_details()

    def center_customization(self, center_id: int) -> dict[str, Any]:
        """Fetch the family customized for one center."""
        self._checked_details()
        self._checked_center(center_id)
        details = self._client.get(
            f"{self._base_path}/centers/{center_id}/customize"
        )
        return _validate_installation_record(
            details, self.id, self._installation_id, "medicine family"
        )

    def __repr__(self) -> str:
        return f"InstallationMedicineFamily(id={self.id})"


class HolidayReasons(DirectResource):
    """Installation holiday reasons.

    `GET .../holiday-reasons` returns an `items` envelope directly. The patient
    form also exposes create and delete actions.
    """

    path = "holiday-reasons"
    default_items_per_page = None

    def create(self, *, description: str) -> Any:
        """Create a reason, including this installation id in the body."""
        installation_id = int(self._base_path.rsplit("/", 1)[-1])
        return self._client.post(
            f"{self.url}/create",
            json={
                "description": description,
                "installation_id": installation_id,
            },
        )

    def delete(self, reason_id: int) -> Any:
        """Delete a holiday reason — `DELETE .../{id}/delete`."""
        return self._client.request("DELETE", f"{self.url}/{reason_id}/delete")


class HospitalizationMotivations(Resource):
    """Installation hospitalization motivations (`.../search` plus writes)."""

    path = "hospitalization-motivations"

    def create(self, *, description: str) -> Any:
        """Create a hospitalization motivation."""
        return self._client.post(
            f"{self.url}/create", json={"description": description}
        )

    def delete(self, motivation_id: int) -> Any:
        """Delete a hospitalization motivation."""
        return self._client.request("DELETE", f"{self.url}/{motivation_id}/delete")


class ProductionLayouts(BareListResource):
    """Production layouts available in an installation.

    `/installations/{id}/production-layouts`

    Bare list, used by the center information and configuration forms. Each
    row includes its `id`, `name`, capacity fields and layout flags.
    """

    path = "production-layouts"


class ProductionSorts(BareListResource):
    """Production sorting strategies available in an installation.

    `/installations/{id}/production-sorts`

    Bare list, used by the center configuration form. Each row includes its
    `id`, `name` and ordered sorting `items`.
    """

    path = "production-sorts"


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

        installation = client.installation(installation_id)

    Attributes:
        id: The installation id, as it appears in the URL.
        centers: See `Centers`; for one center's full scope use `center(id)`.
        cassettes: See `Cassettes`.
        machines: See `Machines`.
        administration_routes: See `AdministrationRoutes`.
        medication_providers: See `MedicationProviders`.
        medicines: See `Medicines`; use `medicine(id)` for one.
        medicine_family_levels: See `MedicineFamilyLevels`.
        medicine_families: See `MedicineFamilies`; use `medicine_family(id)`
            for one.
        medicines_families: See `MedicinesFamilies`.
        holiday_reasons: See `HolidayReasons`.
        hospitalization_motivations: See `HospitalizationMotivations`.
        production_layouts: See `ProductionLayouts`.
        production_sorts: See `ProductionSorts`.
        layouts: See `Layouts`.
        trays: See `Trays`.
        warehouses: See `Warehouses`.

    Example:
        ```python
        installation = client.installation(installation_id)
        print(sorted(installation.details()))
        for cassette in installation.cassettes.list(is_active=True):
            ...
        ```
    """

    def __init__(self, client: "AmcoClient", installation_id: int) -> None:
        self._client = client
        self.id = installation_id
        self._base_path = f"/installations/{installation_id}"

        self.centers = Centers(client, self._base_path)
        self.cassettes = Cassettes(client, self._base_path)
        self.machines = Machines(client, self._base_path)
        self.administration_routes = AdministrationRoutes(client, self._base_path)
        self.medication_providers = MedicationProviders(client, self._base_path)
        self.medicines = Medicines(client, self._base_path)
        self.medicine_family_levels = MedicineFamilyLevels(client, self._base_path)
        self.medicine_families = MedicineFamilies(client, self._base_path)
        self.medicines_families = MedicinesFamilies(client, self._base_path)
        self.holiday_reasons = HolidayReasons(client, self._base_path)
        self.hospitalization_motivations = HospitalizationMotivations(
            client, self._base_path
        )
        self.production_layouts = ProductionLayouts(client, self._base_path)
        self.production_sorts = ProductionSorts(client, self._base_path)
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

    def import_sales(self, document: Mapping[str, Any] | list[Any]) -> Any:
        """Import an installation-wide sales document.

        `POST /installations/{i}/import-sales`

        The body is the opaque JSON document produced by the upstream sales
        system. This can affect multiple patients and is not a preview or
        validation call.
        """
        if isinstance(document, Mapping):
            payload: Any = dict(document)
        else:
            payload = list(document)
        return self._client.post(f"{self._base_path}/import-sales", json=payload)

    def update_sale_line_counter(
        self,
        sale_id: int,
        sale_line_id: int,
        *,
        should_sum_to_counters: bool,
        allow_unverified_scope: bool = False,
    ) -> Any:
        """Change whether a sale line contributes to counters.

        The patient Sales tab supplies both ids, but there is no verified
        installation-scoped item lookup with which the SDK can prove their
        relationship. Derive them from a trusted sales row and opt in
        explicitly with `allow_unverified_scope=True`.
        """
        if not allow_unverified_scope:
            raise ValueError(
                "sale-line update requires allow_unverified_scope=True and trusted ids"
            )
        return self._client.request(
            "PUT",
            f"{self._base_path}/sales/{sale_id}/sale-lines/{sale_line_id}/update",
            json={"should_sum_to_counters": should_sum_to_counters},
        )

    def medicines_in_family(self, medicine_id: int) -> list[dict[str, Any]]:
        """Return medicines in the selected medicine's family.

        `GET /installations/{i}/medicines/{m}/medicines-in-family`
        """
        return self.medicine(medicine_id).medicines_in_family()

    def medicine(self, medicine_id: int) -> InstallationMedicine:
        """Return an installation medicine scope without making a request."""
        return InstallationMedicine(self._client, self._base_path, medicine_id)

    def medicine_family(self, family_id: int) -> InstallationMedicineFamily:
        """Return an installation medicine-family scope without a request."""
        return InstallationMedicineFamily(self._client, self._base_path, family_id)

    def ws_treatments(
        self,
        cic_ids: list[str | int],
        *,
        allow_possible_side_effect: bool = False,
    ) -> Any:
        """Fetch upstream treatment synchronization data for CIC ids.

        `GET /installations/{i}/ws-treatment?cic_ids[]=...`

        This is the GET used by the treatment synchronization button. Its
        server-side effects, if any, have not been verified, so callers must
        opt in explicitly after deriving the CIC ids from trusted state.
        """
        if not allow_possible_side_effect:
            raise ValueError("ws-treatment requires allow_possible_side_effect=True")
        params = [("cic_ids[]", cic_id) for cic_id in cic_ids]
        return self._client.get(f"{self._base_path}/ws-treatment", params=params)

    def __repr__(self) -> str:
        return f"Installation(id={self.id})"
