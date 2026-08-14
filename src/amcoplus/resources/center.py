"""Center (residence) scope, its patients, and per-patient resources."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from .base import BareListResource, Resource, WritableBareListResource
from .patient import Patient, Patients, Treatment, Treatments

if TYPE_CHECKING:
    from ..client import AmcoClient
    from .root import AuthFormField, IntegrationProvider

__all__ = [
    "Center",
    "CenterMedicine",
    "DoseIntervals",
    "Doctors",
    "ImportedMedicines",
    "IntakesAssociation",
    "IntakesGrouping",
    "Integrations",
    "Module",
    "Modules",
    "Patient",
    "Patients",
    "Submodules",
    "Treatment",
    "Treatments",
]


class _CenterScopeGuard:
    """Best-effort guard for the backend's weak installation/center scoping."""

    def __init__(self, client: "AmcoClient", center_path: str) -> None:
        installation_path, center_segment = center_path.rsplit("/centers/", 1)
        self._client = client
        self.center_path = center_path
        self.center_id = int(center_segment)
        self.installation_id = int(installation_path.rsplit("/installations/", 1)[-1])
        self._details: dict[str, Any] | None = None

    def details(self, *, refresh: bool = True) -> dict[str, Any]:
        """Fetch the center and validate both ids returned by the API."""
        if self._details is not None and not refresh:
            return self._details
        details = self._client.get(self.center_path)
        if not isinstance(details, dict):
            raise TypeError("center detail response is not an object")
        center_id = details.get("id")
        installation_id = details.get("installation_id")
        if (
            not isinstance(center_id, int)
            or isinstance(center_id, bool)
            or center_id != self.center_id
            or not isinstance(installation_id, int)
            or isinstance(installation_id, bool)
            or installation_id != self.installation_id
        ):
            raise ValueError("center does not belong to the scoped installation")
        self._details = details
        return details

    def ensure(self, *, refresh: bool = False) -> None:
        """Validate once for reads and freshly before mutations."""
        self.details(refresh=refresh)


class _CenterScopedClient:
    """Client proxy that validates center ownership before nested requests."""

    def __init__(self, client: "AmcoClient", guard: _CenterScopeGuard) -> None:
        self._client = client
        self._guard = guard

    def get(self, endpoint: str, **kwargs: Any) -> Any:
        if endpoint == self._guard.center_path:
            return self._guard.details(refresh=True)
        self._guard.ensure()
        return self._client.get(endpoint, **kwargs)

    def post(self, endpoint: str, **kwargs: Any) -> Any:
        self._guard.ensure(refresh=True)
        return self._client.post(endpoint, **kwargs)

    def request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        if method.upper() == "GET" and endpoint == self._guard.center_path:
            return self._guard.details(refresh=True)
        self._guard.ensure(refresh=method.upper() not in {"GET", "HEAD", "OPTIONS"})
        return self._client.request(method, endpoint, **kwargs)

    def get_bytes(self, endpoint: str, **kwargs: Any) -> bytes:
        self._guard.ensure()
        return self._client.get_bytes(endpoint, **kwargs)

    def request_bytes(self, method: str, endpoint: str, **kwargs: Any) -> bytes:
        self._guard.ensure(refresh=method.upper() not in {"GET", "HEAD", "OPTIONS"})
        return self._client.request_bytes(method, endpoint, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


def _center_row(items: Any, resource_id: int, label: str) -> dict[str, Any]:
    """Locate one id in a center-scoped collection without an item GET."""
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
    raise ValueError(f"{label} does not belong to the scoped center")


def _reject_conflicting_id(
    fields: Mapping[str, Any], key: str, expected: int
) -> dict[str, Any]:
    """Copy fields while rejecting a conflicting nested identity."""
    body = dict(fields)
    supplied = body.get(key)
    if supplied is not None and (
        not isinstance(supplied, int)
        or isinstance(supplied, bool)
        or supplied != expected
    ):
        raise ValueError(f"{key} does not match the scoped resource")
    return body


def _validate_installation_item(
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


class _ScopedWritableBareListResource(WritableBareListResource):
    """Bare center collection whose item writes require list membership."""

    @property
    def center_id(self) -> int:
        center_segment = self._base_path.split("/centers/", 1)[-1].split("/", 1)[0]
        return int(center_segment)

    def _find(self, resource_id: int) -> dict[str, Any]:
        return _center_row(self.list(), resource_id, type(self).__name__)

    def get(self, resource_id: int) -> dict[str, Any]:
        """Return an item only from this center's collection."""
        return self._find(resource_id)

    def create(self, **fields: Any) -> Any:
        """Create after rejecting a conflicting body-level center id."""
        body = _reject_conflicting_id(fields, "center_id", self.center_id)
        return self._client.post(f"{self.url}/create", json=body)

    def update(self, resource_id: int, **fields: Any) -> Any:
        """Update only an id present in this center's collection."""
        self._find(resource_id)
        body = _reject_conflicting_id(fields, "id", resource_id)
        body = _reject_conflicting_id(body, "center_id", self.center_id)
        return self._client.request(
            "PUT", f"{self.url}/{resource_id}/update", json=body
        )


class Integrations(BareListResource):
    """Integrations configured on a center — the provider customizations.

    `/installations/{i}/centers/{c}/integration-provider-customizations`

    This is the INTEGRATIONS tab of a center: each row wires the center to one
    provider (from `client.root.integration_providers(...)`) with a schedule.
    One generic endpoint serves every category and every provider — the
    category and provider are not in the path, only `integration_provider_id`
    in the body — so `create` covers all of them. The collection GET returns a
    bare list — no `/search`, no `{"items": ...}` envelope. Writes do not follow
    the usual POST-to-subpath convention: `update` is a PUT and `delete` an HTTP
    DELETE (see those methods).

    The library does not judge whether an integration will actually work:
    `create` sends whatever you give it, even a half-filled or wrong credential.
    Whether the far end then connects is the provider's and the operator's
    problem, not this library's. `credential_template` and
    `missing_credential_fields` are there to make the call easy and to *warn*,
    never to block it.
    """

    path = "integration-provider-customizations"

    def _find(self, integration_id: int) -> dict[str, Any]:
        """Locate an integration in this center's bare collection."""
        return _center_row(self.list(), integration_id, "integration")

    def get(self, resource_id: int) -> dict[str, Any]:
        """Return an integration only from this center's collection."""
        return self._find(resource_id)

    # auth_form entries that are not create-time credential inputs: `message`
    # is help text, and a `file` field (e.g. a production `file`) is the data
    # channel — the integration exposes an upload URL for it, it is not sent
    # with create. Anything without a real `name` is UI noise (`undefined`).
    _NON_CREDENTIAL_TYPES = frozenset({"message", "file"})

    @classmethod
    def _credential_fields(
        cls, provider: "IntegrationProvider"
    ) -> list[dict[str, Any]]:
        """The `auth_form` entries that are real create-time credential inputs."""
        return [
            field
            for field in provider.get("auth_form", [])
            if field.get("name")
            and field["name"] != "undefined"
            and field.get("type") not in cls._NON_CREDENTIAL_TYPES
        ]

    @staticmethod
    def select_choices(field: "AuthFormField") -> dict[Any, str]:
        """Valid values of a `select` field, as `{value_to_send: label}`.

        Reads the field's `items` (`[{key, value}]`, where `key` is what goes in
        `auth_credential` and `value` is the display label). For example, a
        `protocol` field returns `{"http": "HTTP", "https": "HTTPS", ...}`.

        Empty for a **dynamic** select — one whose `options` is `{"action": ...}`,
        whose choices are fetched live. Get those with `execute_action` instead,
        passing `field["options"]["action"]`.
        """
        return {c["key"]: c.get("value") for c in field.get("items") or []}

    @classmethod
    def credential_template(cls, provider: "IntegrationProvider") -> dict[str, None]:
        """A blank `auth_credential` for a provider, keyed by its input fields.

        Returns `{field_name: None}` for every credential field the provider
        declares — the scalar inputs (text/number/password/select/checkbox),
        skipping help text and file fields — so you can see what to fill:

            prov = client.root.integration_providers("productions").get(1)
            cred = center.integrations.credential_template(prov)
            # {'host': None, 'port': None, ... 'password': None, ...}
            cred["host"] = "..."          # fill what you have
            center.integrations.create(integration_provider_id=prov["id"],
                                       auth_credential=cred)

        A convenience only — you may pass any dict to `create`. Inspect the
        provider's `auth_form` (or `client.root.integration_provider_form`) for
        each field's `type` and `options`, e.g. the choices of a `select`.
        """
        return {field["name"]: None for field in cls._credential_fields(provider)}

    @classmethod
    def missing_credential_fields(
        cls, provider: "IntegrationProvider", auth_credential: Mapping[str, Any]
    ) -> list[str]:
        """Names of the provider's required input fields left empty.

        A non-blocking check: it *reports*, it does not raise. An empty list
        means every required credential field has a non-empty value; otherwise
        you get the field `name`s still missing, to warn on before (or after)
        creating. Help text and file fields are not counted. `create` never
        calls this itself.
        """
        return [
            field["name"]
            for field in cls._credential_fields(provider)
            if field.get("is_required") and not auth_credential.get(field["name"])
        ]

    @staticmethod
    def _body(
        integration_provider_id: int,
        auth_credential: Mapping[str, Any] | None,
        type_frequency: str,
        frequency: str,
        at_day: int | None,
        at_hour: int | None,
        at_minute: int | None,
    ) -> dict[str, Any]:
        return {
            "integration_provider_id": integration_provider_id,
            "auth_credential": dict(auth_credential) if auth_credential else {},
            "type_frequency": type_frequency,
            "frequency": frequency,
            "at_day": at_day,
            "at_hour": at_hour,
            "at_minute": at_minute,
        }

    def create(
        self,
        *,
        integration_provider_id: int,
        auth_credential: Mapping[str, Any] | None = None,
        type_frequency: str = "manual",
        frequency: str = "weekly",
        at_day: int | None = None,
        at_hour: int | None = None,
        at_minute: int | None = None,
    ) -> dict[str, Any]:
        """Wire this center to an integration provider — always sends the POST.

        `POST .../integration-provider-customizations/create`

        No validation happens here: whatever you pass is sent as-is. Missing or
        wrong credentials still create the row; the integration simply won't
        sync until a human fixes it on the provider side. Use
        `missing_credential_fields` first if you want to warn.

        Args:
            integration_provider_id: `id` of the chosen provider, from
                `client.root.integration_providers(category).list()`.
            auth_credential: The provider's credential fields, keyed by the
                `name`s in its `auth_form`. Omit for providers that need none;
                partial or empty is accepted.
            type_frequency: How the sync is triggered, e.g. `"manual"`.
            frequency: Sync cadence when it is not manual, e.g. `"weekly"`.
            at_day, at_hour, at_minute: When to run a scheduled sync; leave
                `None` for `"manual"`.

        Returns:
            The created integration record (with its new `id`), so you can
            confirm what was stored or act on it. The API wraps the row in a
            `{"data": ...}` envelope on create; this unwraps it. For a
            file/webhook provider the record also carries the ingest URLs —
            `public_url_absolute` (the webhook to POST data to),
            `private_url_absolute`, `public_soap_url_absolute` and
            `url_signature`. The integration only takes effect once `check`
            passes.
        """
        body = self._body(
            integration_provider_id,
            auth_credential,
            type_frequency,
            frequency,
            at_day,
            at_hour,
            at_minute,
        )
        result = self._client.post(f"{self.url}/create", json=body)
        if isinstance(result, dict) and "data" in result:
            return result["data"]
        return result

    def update(
        self,
        integration_id: int,
        *,
        integration_provider_id: int,
        auth_credential: Mapping[str, Any] | None = None,
        type_frequency: str = "manual",
        frequency: str = "weekly",
        at_day: int | None = None,
        at_hour: int | None = None,
        at_minute: int | None = None,
    ) -> Any:
        """Replace one integration's configuration.

        `PUT .../integration-provider-customizations/{integration_id}/update`

        This resource breaks the usual POST-to-`/update` convention: update is
        an HTTP **PUT**, and it wants the **whole** body (the same fields as
        `create`), not a partial one — a partial body 500s. Pass every field,
        including the ones you are not changing.
        """
        self._find(integration_id)
        body = self._body(
            integration_provider_id,
            auth_credential,
            type_frequency,
            frequency,
            at_day,
            at_hour,
            at_minute,
        )
        return self._client.request(
            "PUT", f"{self.url}/{integration_id}/update", json=body
        )

    def delete(self, integration_id: int) -> Any:
        """Deactivate one integration.

        `DELETE .../integration-provider-customizations/{integration_id}/delete`

        Another break from convention: delete is an HTTP **DELETE**, not a POST.
        It is a **soft delete** — the row's `is_active` becomes `False` and it
        stops showing in the UI, but `list()` still returns it. Amco+ exposes no
        hard delete for integrations.
        """
        self._find(integration_id)
        return self._client.request("DELETE", f"{self.url}/{integration_id}/delete")

    def check(self, integration_id: int) -> Any:
        """Test an integration's connection — the "Comprobar conexión" button.

        `POST .../integration-provider-customizations/{integration_id}/check`

        A freshly created integration does not take effect until its connection
        checks out, so call this after `create`. Returns `{"accepted": bool,
        "reason": ...}` when the test runs. A provider that cannot connect (wrong
        credentials, unreachable host) may instead answer HTTP 500, which surfaces
        as `APIError`.
        """
        self._find(integration_id)
        return self._client.post(f"{self.url}/{integration_id}/check")

    def execute_action(
        self,
        integration_id: int,
        action: str,
        attributes: Mapping[str, Any] | None = None,
    ) -> Any:
        """Run a provider action on an integration — how dynamic options load.

        `POST .../integration-provider-customizations/{integration_id}/execute-action`

        Some `auth_form` fields are dependent dropdowns: their `options` is not a
        static list but `{"action": "<name>"}`, and the choices are fetched live
        from the far end. Resiplus's `resiplus_center` (action `request_centers`)
        is the example — the server connects with the given credentials and
        returns the centres to pick from.

        Args:
            integration_id: An existing integration's id. The action runs against
                a stored row; a not-yet-created one has no id to act on.
            action: The action name from the field's `options["action"]`.
            attributes: The field values the action needs (e.g. host, port, user,
                password), as a plain mapping. Sent as the API's
                `[{"key": ..., "value": ...}]` list for you.

        Returns:
            The action's result — for `request_centers`, the list of choices.
        """
        self._find(integration_id)
        payload = {
            "action": action,
            "attributes": [
                {"key": key, "value": value}
                for key, value in (attributes or {}).items()
            ],
        }
        return self._client.post(
            f"{self.url}/{integration_id}/execute-action", json=payload
        )


class Doctors(_ScopedWritableBareListResource):
    """Doctors of a center — `/installations/{i}/centers/{c}/doctors`.

    Bare list. `create`/`update` (PUT) work; the endpoint has no delete.
    """

    path = "doctors"

    def specializations(self) -> list[dict[str, Any]]:
        """Return the bare doctor-specialization lookup for this center."""
        return self._client.get(f"{self.url}/specializations")


class DoseIntervals(BareListResource):
    """Allowed dose intervals for a medicine or medicine family.

    `GET .../centers/{c}/dose-intervals`, filtered by either `medicine_id` or
    `medicine_family_id`. This lookup is used by the treatment editor.
    """

    path = "dose-intervals"

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        """List intervals after validating an optional medicine/family id."""
        medicine_id = filters.get("medicine_id")
        family_id = filters.get("medicine_family_id")
        if medicine_id is not None and family_id is not None:
            raise ValueError("pass medicine_id or medicine_family_id, not both")

        installation_path = self._base_path.split("/centers/", 1)[0]
        installation_id = int(installation_path.rsplit("/", 1)[-1])
        if medicine_id is not None:
            details = self._client.get(
                f"{installation_path}/medicines/{medicine_id}"
            )
            _validate_installation_item(
                details, medicine_id, installation_id, "medicine"
            )
        if family_id is not None:
            details = self._client.get(
                f"{installation_path}/medicine-families/{family_id}"
            )
            _validate_installation_item(
                details, family_id, installation_id, "medicine family"
            )
        return super().list(**filters)


class Modules(_ScopedWritableBareListResource):
    """Modules of a center — `/installations/{i}/centers/{c}/modules`.

    Bare list, with `create` and `update` (PUT). No delete. Reach a module's
    submodules through `center.module(m).submodules`.
    """

    path = "modules"


class Submodules(_ScopedWritableBareListResource):
    """Submodules of a module.

    `/installations/{i}/centers/{c}/modules/{m}/submodules`

    Bare list, with `create`, `update` (PUT) and `delete` (DELETE) — the one
    center resource here that supports deletion.
    """

    path = "submodules"

    def __init__(self, client: "AmcoClient", base_path: str) -> None:
        super().__init__(client, base_path)
        center_path, module_segment = base_path.rsplit("/modules/", 1)
        self.module_id = int(module_segment)
        self._modules = Modules(client, center_path)

    def _ensure_module(self) -> None:
        """Require the parent module in this center's collection."""
        self._modules._find(self.module_id)

    def list(self, **filters: Any) -> list[dict[str, Any]]:
        """List submodules only after proving the parent module."""
        self._ensure_module()
        return super().list(**filters)

    def create(self, **fields: Any) -> Any:
        """Create a submodule bound to the verified parent module."""
        self._ensure_module()
        body = _reject_conflicting_id(fields, "module_id", self.module_id)
        return super().create(**body)

    def update(self, resource_id: int, **fields: Any) -> Any:
        """Update a submodule from this verified module's collection."""
        body = _reject_conflicting_id(fields, "module_id", self.module_id)
        return super().update(resource_id, **body)

    def delete(self, submodule_id: int) -> Any:
        """Delete a submodule — `DELETE .../submodules/{submodule_id}/delete`."""
        self._find(submodule_id)
        return self._delete(submodule_id)


class ImportedMedicines(Resource):
    """Imported medicines of a center — `.../imported-medicines/search`.

    Unlike most center collections this one paginates (envelope with `items`).

    Filters:
        not_associated (bool): Only medicines not yet linked to a real one.
    """

    path = "imported-medicines"

    def get(self, resource_id: int) -> dict[str, Any]:
        """Return an item only from this center's paginated collection."""
        result = self.search(all_items=True)
        if not isinstance(result, dict):
            raise TypeError("imported-medicine search response is not an object")
        return _center_row(result.get("items"), resource_id, "imported medicine")


class IntakesAssociation(_ScopedWritableBareListResource):
    """A center's intakes — the medication times ("tomas").

    `/installations/{i}/centers/{c}/intakes-association`

    Bare list, with `create` (POST) and `update` (PUT); no delete. Each item is
    a time slot: `name`, `time`, `hour`, `minute`, `color`, `is_active`, `url`.

    The real path is `intakes-association`, not the `intakes` the older notes
    guessed. The center-config flags `use_intakes_association` /
    `use_intakes_grouping` toggle the feature but do **not** gate this endpoint —
    it answers whether they are on or off.
    """

    path = "intakes-association"


class IntakesGrouping(_ScopedWritableBareListResource):
    """A center's intake groupings — `.../intakes-grouping`.

    Bare list, with `create` (POST) and `update` (PUT); no delete. The real path
    is `intakes-grouping`, not the `intake-agrupations` the older notes guessed,
    and it too answers regardless of the center-config flags.
    """

    path = "intakes-grouping"


class CenterMedicine:
    """A medicine seen and customised from one center.

    The medicine itself is installation-level; these two endpoints are its
    **per-center** view and overrides. Get one from a center rather than
    building it directly:

        med = (
            client.installation(installation_id)
            .center(center_id)
            .medicine(medicine_id)
        )

    Attributes:
        id: The medicine id (an installation-level medicine id).
    """

    def __init__(self, client: "AmcoClient", base_path: str, medicine_id: int) -> None:
        self._client = client
        self.id = medicine_id
        self._base_path = f"{base_path}/medicines/{medicine_id}"
        installation_path = base_path.split("/centers/", 1)[0]
        self._installation_id = int(
            installation_path.rsplit("/installations/", 1)[-1]
        )

    def _checked_customized(self) -> dict[str, Any]:
        """Fetch and reject a medicine resolved from another installation."""
        details = self._client.get(f"{self._base_path}/customized")
        return _validate_installation_item(
            details,
            self.id,
            self._installation_id,
            "medicine",
        )

    def customized(self) -> dict[str, Any]:
        """This medicine as this center sees it.

        `GET /installations/{i}/centers/{c}/medicines/{id}/customized`

        Returns the medicine record with the center's overrides applied
        (flags like `is_emblistable`, `can_use_fsp`, `force_dispense_in_tray`,
        `dispense_in_unique_bag`, ...).
        """
        return self._checked_customized()

    def customize(self, **fields: Any) -> Any:
        """Apply this center's overrides to the medicine.

        `PUT /installations/{i}/centers/{c}/medicines/{id}/customize`

        A **PUT** (POST → 405), returns 202. Pass the fields to override; the
        keys are the writable ones from `customized()`.
        """
        if {"id", "installation_id", "center_id"}.intersection(fields):
            raise ValueError("customize accepts override fields, not identity ids")
        self._checked_customized()
        return self._client.request(
            "PUT", f"{self._base_path}/customize", json=fields
        )

    def __repr__(self) -> str:
        return f"CenterMedicine(id={self.id})"


class Module:
    """A single module of a center. Its submodules hang off here.

    Get one from a center rather than building it directly:

        module = (
            client.installation(installation_id)
            .center(center_id)
            .module(module_id)
        )

    Attributes:
        id: The module id, as it appears in the URL.
        submodules: See `Submodules`.
    """

    def __init__(self, client: "AmcoClient", base_path: str, module_id: int) -> None:
        self._client = client
        self.id = module_id
        self._base_path = f"{base_path}/modules/{module_id}"

        self.submodules = Submodules(client, self._base_path)

    def __repr__(self) -> str:
        return f"Module(id={self.id})"


class Center:
    """A residence served by an installation. Patient-level resources live here.

    Get one from an installation rather than building it directly:

        center = client.installation(installation_id).center(center_id)

    Attributes:
        id: The center id, as it appears in the URL.
        patients: See `Patients`.
        integrations: See `Integrations`.
        doctors: See `Doctors`.
        dose_intervals: See `DoseIntervals`.
        modules: See `Modules`; a module's submodules are under `module(m)`.
        imported_medicines: See `ImportedMedicines`.
        intakes_association: See `IntakesAssociation` (the "tomas").
        intakes_grouping: See `IntakesGrouping`.

    Its own record is `details()`, and `update()` changes its configuration.

    Example:
        ```python
        center = client.installation(installation_id).center(center_id)
        print(sorted(center.details()))
        center.update(use_intakes_association=True)

        page = center.patients.search(all_items=False, page=1, is_active=True)
        for patient in page["items"]:
            print(patient["id"])
        ```
    """

    def __init__(self, client: "AmcoClient", base_path: str, center_id: int) -> None:
        self.id = center_id
        self._base_path = f"{base_path}/centers/{center_id}"
        self._scope_guard = _CenterScopeGuard(client, self._base_path)
        self._client = _CenterScopedClient(client, self._scope_guard)

        self.patients = Patients(self._client, self._base_path)
        self.integrations = Integrations(self._client, self._base_path)
        self.doctors = Doctors(self._client, self._base_path)
        self.dose_intervals = DoseIntervals(self._client, self._base_path)
        self.modules = Modules(self._client, self._base_path)
        self.imported_medicines = ImportedMedicines(self._client, self._base_path)
        self.intakes_association = IntakesAssociation(self._client, self._base_path)
        self.intakes_grouping = IntakesGrouping(self._client, self._base_path)

    def details(self) -> dict[str, Any]:
        """Fetch this center's own record — `GET /installations/{i}/centers/{c}`.

        Returns the full center object: name, contact fields, the production
        defaults, and the config flags (`use_intakes_association`,
        `use_intakes_grouping`, `use_families_for_productions`, ...). Some fields
        are read-only (`active_patients_count`, `last_synchronization_*`).
        """
        return self._client.get(self._base_path)

    def update(self, **fields: Any) -> Any:
        """Update this center's configuration.

        `PUT /installations/{i}/centers/{c}/update`

        Breaks the usual POST-to-`/update` convention: it is an HTTP **PUT**
        (POST gives 405). It takes a **partial** body — pass only the fields to
        change and the rest are left untouched, e.g.
        `center.update(use_intakes_association=True)`. The accepted keys are the
        writable fields from `details()`.
        """
        return self._client.request("PUT", f"{self._base_path}/update", json=fields)

    def import_patients_and_treatments(self) -> Any:
        """Import patients and treatments from the center's supplier integration.

        `POST /installations/{i}/centers/{c}/import-patients-and-treatments`

        An action, not CRUD: it pulls from the center's configured
        patients-and-treatments **supplier** integration. Without one, the API
        answers HTTP 500 / `error_code` 87006.
        """
        return self._client.post(f"{self._base_path}/import-patients-and-treatments")

    def import_patient_counters(self) -> Any:
        """Import patient counter data from the configured integration.

        `POST /installations/{i}/centers/{c}/import-patients-counters`
        """
        return self._client.post(f"{self._base_path}/import-patients-counters")

    def associate_treatments(self) -> Any:
        """Associate pending imported treatments for this center.

        `POST /installations/{i}/centers/{c}/associate-treatments`

        This is a mutating center-wide action with no preview endpoint.
        """
        return self._client.post(f"{self._base_path}/associate-treatments")

    def module(self, module_id: int) -> "Module":
        """Return a `Module` scoped to this center, for its submodules.

        No request is made; the scope is built locally.
        """
        return Module(self._client, self._base_path, module_id)

    def medicine(self, medicine_id: int) -> "CenterMedicine":
        """Return a `CenterMedicine` — a medicine's per-center view and overrides.

        No request is made; the scope is built locally.
        """
        return CenterMedicine(self._client, self._base_path, medicine_id)

    def patient(self, patient_id: int) -> "Patient":
        """Return a `Patient` scoped to this center.

        No request is made; the scope is built locally.
        """
        return Patient(self._client, self._base_path, patient_id)

    def __repr__(self) -> str:
        return f"Center(id={self.id})"
