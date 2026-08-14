"""Center (residence) scope, its patients, and per-patient resources."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

from .base import BareListResource, Resource

if TYPE_CHECKING:
    from ..client import AmcoClient
    from .root import IntegrationProvider

__all__ = [
    "Center",
    "Integrations",
    "Patient",
    "Patients",
    "Treatments",
]


class Patients(Resource):
    """Patients of a center — `/installations/{i}/centers/{c}/patients/search`.

    Filters:
        is_active (bool): Only active patients.
        query (str): Free-text search.
    """

    path = "patients"


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

    @classmethod
    def credential_template(
        cls, provider: "IntegrationProvider"
    ) -> dict[str, None]:
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
            The created integration record, so you can confirm what was stored.
        """
        body = self._body(
            integration_provider_id, auth_credential, type_frequency,
            frequency, at_day, at_hour, at_minute,
        )
        return self._client.post(f"{self.url}/create", json=body)

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
        body = self._body(
            integration_provider_id, auth_credential, type_frequency,
            frequency, at_day, at_hour, at_minute,
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
        return self._client.request(
            "DELETE", f"{self.url}/{integration_id}/delete"
        )

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


class Treatments(Resource):
    """Treatments of a patient.

    `/installations/{i}/centers/{c}/patients/{p}/treatments/search`
    """

    path = "treatments"


class Center:
    """A residence served by an installation. Patient-level resources live here.

    Get one from an installation rather than building it directly:

        center = client.installation(65).center(417)

    Attributes:
        id: The center id, as it appears in the URL.
        patients: See `Patients`.
        integrations: See `Integrations`.

    Example:
        ```python
        center = client.installation(65).center(417)
        for patient in center.patients.list(is_active=True):
            print(patient["id"])

        for integration in center.integrations.list():
            print(integration["id"])
        ```
    """

    def __init__(self, client: "AmcoClient", base_path: str, center_id: int) -> None:
        self._client = client
        self.id = center_id
        self._base_path = f"{base_path}/centers/{center_id}"

        self.patients = Patients(client, self._base_path)
        self.integrations = Integrations(client, self._base_path)

    def patient(self, patient_id: int) -> "Patient":
        """Return a `Patient` scoped to this center.

        No request is made; the scope is built locally.
        """
        return Patient(self._client, self._base_path, patient_id)

    def __repr__(self) -> str:
        return f"Center(id={self.id})"


class Patient:
    """A single patient. Treatment-level resources hang off here.

    Get one from a center rather than building it directly:

        patient = client.installation(65).center(417).patient(3955)

    Attributes:
        id: The patient id, as it appears in the URL.
        treatments: See `Treatments`.
    """

    def __init__(self, client: "AmcoClient", base_path: str, patient_id: int) -> None:
        self._client = client
        self.id = patient_id
        self._base_path = f"{base_path}/patients/{patient_id}"

        self.treatments = Treatments(client, self._base_path)

    def __repr__(self) -> str:
        return f"Patient(id={self.id})"
