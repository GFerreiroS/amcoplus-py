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
    The collection GET returns a bare list — no `/search`, no `{"items": ...}`
    envelope. Writes follow the usual `create` / `{id}/update` / `{id}/delete`
    POST convention.

    The library does not judge whether an integration will actually work:
    `create` sends whatever you give it, even a half-filled or wrong credential.
    Whether the far end then connects is the provider's and the operator's
    problem, not this library's. `credential_template` and
    `missing_credential_fields` are there to make the call easy and to *warn*,
    never to block it.
    """

    path = "integration-provider-customizations"

    @staticmethod
    def credential_template(provider: "IntegrationProvider") -> dict[str, None]:
        """A blank `auth_credential` for a provider, keyed by its `auth_form`.

        Returns `{field_name: None}` for every field the provider declares, so
        you can see what to fill in without reading the raw `auth_form`:

            prov = client.root.integration_providers("productions").get(6)
            cred = center.integrations.credential_template(prov)
            cred["username"] = "..."     # fill what you have
            center.integrations.create(integration_provider_id=prov["id"],
                                       auth_credential=cred)

        A convenience only — you may pass any dict to `create`.
        """
        return {field["name"]: None for field in provider.get("auth_form", [])}

    @staticmethod
    def missing_credential_fields(
        provider: "IntegrationProvider", auth_credential: Mapping[str, Any]
    ) -> list[str]:
        """Names of the provider's required fields left empty in a credential.

        A non-blocking check: it *reports*, it does not raise. An empty list
        means every `is_required` field has a non-empty value; otherwise you get
        the field `name`s still missing, to warn on before (or after) creating.
        `create` never calls this itself.
        """
        return [
            field["name"]
            for field in provider.get("auth_form", [])
            if field.get("is_required")
            and not auth_credential.get(field["name"])
        ]

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
        body = {
            "integration_provider_id": integration_provider_id,
            "auth_credential": dict(auth_credential) if auth_credential else {},
            "type_frequency": type_frequency,
            "frequency": frequency,
            "at_day": at_day,
            "at_hour": at_hour,
            "at_minute": at_minute,
        }
        return self._client.post(f"{self.url}/create", json=body)

    def update(self, integration_id: int, **fields: Any) -> dict[str, Any]:
        """Update one integration — `.../{integration_id}/update`.

        Pass only the fields to change; the accepted keys are the same as
        `create`.
        """
        return self._client.post(f"{self.url}/{integration_id}/update", json=fields)

    def delete(self, integration_id: int) -> Any:
        """Remove one integration — `.../{integration_id}/delete`."""
        return self._client.post(f"{self.url}/{integration_id}/delete")


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
