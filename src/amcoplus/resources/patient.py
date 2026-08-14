"""Patient scope and the resources exposed by the patient record tabs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from .base import BareListResource, DirectResource, Resource

if TYPE_CHECKING:
    from ..client import AmcoClient

__all__ = [
    "Allergies",
    "Attachments",
    "Diagnoses",
    "DoseTakesControl",
    "HolidayPeriods",
    "HospitalizationPeriods",
    "Patient",
    "PatientDoctors",
    "Patients",
    "SaleProgramCodes",
    "Sales",
    "Treatment",
    "Treatments",
]

JSONDict = dict[str, Any]


def _scoped_body(
    record: Mapping[str, Any],
    key: str,
    expected: int,
    *,
    inject: bool = True,
) -> JSONDict:
    """Copy a request body while rejecting a conflicting scoped id."""
    body = dict(record)
    supplied = body.get(key)
    if supplied is not None and (
        not isinstance(supplied, int)
        or isinstance(supplied, bool)
        or supplied != expected
    ):
        raise ValueError(f"{key} does not match the scoped resource")
    if inject:
        body[key] = expected
    return body


def _row_by_id(items: Any, resource_id: int, label: str) -> JSONDict:
    """Return one row from a scoped collection without an unsafe item GET."""
    if not isinstance(resource_id, int) or isinstance(resource_id, bool):
        raise ValueError(f"{label} id must be an integer")
    if not isinstance(items, list):
        raise TypeError(f"{label} response is not a list")
    for item in items:
        if isinstance(item, dict):
            item_id = item.get("id")
            if (
                isinstance(item_id, int)
                and not isinstance(item_id, bool)
                and item_id == resource_id
            ):
                return item
    raise ValueError(f"{label} does not belong to the scoped patient")


class _PatientScopeGuard:
    """Best-effort client guard for the backend's weak nested ownership checks."""

    def __init__(self, client: "AmcoClient", patient_path: str) -> None:
        center_path, patient_segment = patient_path.rsplit("/patients/", 1)
        self._client = client
        self.patient_path = patient_path
        self.center_path = center_path
        self.patient_id = int(patient_segment)
        self.center_id = int(center_path.rsplit("/centers/", 1)[-1])
        installation_path = center_path.split("/centers/", 1)[0]
        self.installation_id = int(
            installation_path.rsplit("/installations/", 1)[-1]
        )
        self._center_verified = False
        self._verified = False

    def _ensure_center(self, *, refresh: bool) -> None:
        """Validate the parent center before downloading patient data."""
        if self._center_verified and not refresh:
            return
        details = self._client.get(self.center_path)
        if not isinstance(details, dict):
            raise TypeError("center detail response is not an object")
        if (
            details.get("id") != self.center_id
            or details.get("installation_id") != self.installation_id
        ):
            raise ValueError("center does not belong to the scoped installation")
        self._center_verified = True

    def details(self, *, refresh: bool = True) -> JSONDict:
        """Fetch and validate both ids carried by the patient detail body."""
        if self._verified and not refresh:
            return {}
        self._ensure_center(refresh=refresh)
        details = self._client.get(self.patient_path)
        if not isinstance(details, dict):
            raise TypeError("patient detail response is not an object")
        if (
            details.get("id") != self.patient_id
            or details.get("center_id") != self.center_id
        ):
            raise ValueError("patient does not belong to the scoped center")
        self._verified = True
        return details

    def ensure(self, *, refresh: bool = False) -> None:
        """Validate the scope once for reads, or freshly before mutations."""
        self.details(refresh=refresh)


class Patients(Resource):
    """Patients of a center.

    The UI uses both `GET .../patients` (a bare list) and
    `GET .../patients/search` (a paginated envelope). `search()` and the
    inherited `list()` use the enveloped route. `direct_list()` exposes the
    envelope-less variant explicitly so callers can distinguish the two shapes.

    Patient rows contain personal and clinical data. Do not log them wholesale.

    Filters confirmed for `/search`:
        is_active (bool): Only active patients.
        query (str): Free-text patient search.
    """

    path = "patients"

    def __init__(self, client: "AmcoClient", base_path: str) -> None:
        super().__init__(client, base_path)
        self.center_id = int(base_path.rsplit("/centers/", 1)[-1])

    def direct_list(self, **filters: Any) -> list[JSONDict]:
        """Return `GET .../patients`, the UI's direct bare-list route."""
        return self._client.get(self.url, params=filters or None)

    def create(self, **fields: Any) -> Any:
        """Create a patient — `POST .../patients/create`.

        The endpoint accepts the patient-form object. Required fields and
        validation rules are installation-specific, so fields pass through
        unchanged.
        """
        body = _scoped_body(fields, "center_id", self.center_id)
        return self._client.post(f"{self.url}/create", json=body)

    def get(self, resource_id: int) -> JSONDict:
        """Fetch a patient and verify the response belongs to this center."""
        return _PatientScopeGuard(self._client, f"{self.url}/{resource_id}").details()


class Treatments(Resource):
    """Treatments belonging to one patient.

    `search()` uses `GET .../treatments/search`; `direct_list()` exposes the
    additional bare-list `GET .../treatments` used by the web client. Search
    and detail responses contain medication, dose and scheduling data.
    """

    path = "treatments"

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        super().__init__(client, base_path)
        self.patient_id = int(base_path.rsplit("/patients/", 1)[-1])
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)

    def _patient_body(self, treatment: Mapping[str, Any]) -> JSONDict:
        """Copy a treatment body and prevent cross-patient assignment."""
        return _scoped_body(treatment, "patient_id", self.patient_id)

    @staticmethod
    def _config_rows(body: JSONDict) -> list[JSONDict]:
        """Copy the required edited configs and require object rows."""
        configs = body.get("configs")
        if not isinstance(configs, list):
            raise TypeError("a complete treatment body requires a configs list")
        rows: list[JSONDict] = []
        for config in configs:
            if not isinstance(config, Mapping):
                raise TypeError("each treatment config must be an object")
            rows.append(dict(config))
        return rows

    def _create_body(self, treatment: Mapping[str, Any]) -> JSONDict:
        """Build a new-treatment body without reusable treatment/config ids."""
        body = self._patient_body(treatment)
        if body.get("id") is not None:
            raise ValueError("a new treatment cannot carry an existing id")
        body.pop("id", None)
        configs = self._config_rows(body)
        for config in configs:
            if config.get("id") is not None or config.get("treatment_id") is not None:
                raise ValueError("a new treatment config cannot carry existing ids")
            config.pop("id", None)
            config["treatment_id"] = None
        body["configs"] = configs
        return body

    def _update_body(self, treatment_id: int, treatment: Mapping[str, Any]) -> JSONDict:
        """Bind a complete treatment/config body to the guarded target id."""
        body = self._patient_body(treatment)
        body = _scoped_body(body, "id", treatment_id)
        configs = self._config_rows(body)
        supplied_ids = {config.get("id") for config in configs} - {None}
        existing_ids: set[int] = set()
        if supplied_ids:
            existing = self._client.get(f"{self.url}/{treatment_id}/treatment-config")
            if not isinstance(existing, list):
                raise TypeError("treatment config response is not a list")
            existing_ids = {
                row["id"]
                for row in existing
                if isinstance(row, dict)
                and isinstance(row.get("id"), int)
                and not isinstance(row["id"], bool)
            }
        for config in configs:
            config_id = config.get("id")
            if config_id is not None:
                if (
                    not isinstance(config_id, int)
                    or isinstance(config_id, bool)
                    or config_id not in existing_ids
                ):
                    raise ValueError(
                        "treatment config does not belong to the scoped treatment"
                    )
            supplied_treatment_id = config.get("treatment_id")
            if supplied_treatment_id is not None and (
                not isinstance(supplied_treatment_id, int)
                or isinstance(supplied_treatment_id, bool)
                or supplied_treatment_id != treatment_id
            ):
                raise ValueError("treatment config points to a different treatment")
            if config_id is None:
                config.pop("id", None)
            config["treatment_id"] = treatment_id
        body["configs"] = configs
        return body

    def _checked_details(self, treatment_id: int) -> JSONDict:
        """Fetch one item and reject the API's cross-patient path behaviour.

        Beta does not enforce the `{patient_id}` segment of the nested detail
        route. A paginated membership search is not a reliable substitute:
        inactive treatments are absent unless specifically requested and the
        free-text `query` filter does not match ids. The smallest reliable
        preflight is therefore the detail response's own `patient_id` field.

        A mismatched response is discarded and never returned to the caller.
        """
        self._scope_guard.ensure()
        details = self._client.get(f"{self.url}/{treatment_id}")
        if not isinstance(details, dict):
            raise TypeError("treatment detail response is not an object")
        if (
            details.get("id") != treatment_id
            or details.get("patient_id") != self.patient_id
        ):
            raise ValueError("treatment does not belong to the scoped patient")
        return details

    def _assert_belongs(self, treatment_id: int) -> JSONDict:
        """Repeat the ownership preflight before an item action."""
        self._scope_guard.ensure(refresh=True)
        return self._checked_details(treatment_id)

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Search treatments only after validating the patient/center scope."""
        self._scope_guard.ensure()
        return super().search(all_items=all_items, **filters)

    def get(self, resource_id: int) -> JSONDict:
        """Fetch a treatment only after verifying patient ownership."""
        return self._checked_details(resource_id)

    def direct_list(self, **filters: Any) -> list[JSONDict]:
        """Return the patient's direct, envelope-less treatment list."""
        self._scope_guard.ensure()
        return self._client.get(self.url, params=filters or None)

    def medical_order(self) -> JSONDict:
        """Return the patient's medical-order treatment projection.

        `GET .../patients/{p}/treatments/medical-order`
        """
        self._scope_guard.ensure()
        return self._client.get(f"{self.url}/medical-order")

    @staticmethod
    def _authentication_headers(
        authenticate_code: str | None,
        step_up_grant: str | None,
    ) -> dict[str, str] | None:
        headers: dict[str, str] = {}
        if authenticate_code is not None:
            headers["authenticateCode"] = authenticate_code
        if step_up_grant is not None:
            headers["X-Step-Up-Grant"] = step_up_grant
        return headers or None

    def create(
        self,
        treatment: Mapping[str, Any],
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Create a treatment, including its `configs` in the complete body.

        Centers configured for treatment 2FA may require `authenticate_code`
        and/or a short-lived `step_up_grant`. They are sent as headers and are
        never stored by the client.
        """
        self._scope_guard.ensure(refresh=True)
        return self._client.post(
            f"{self.url}/create",
            json=self._create_body(treatment),
            headers=self._authentication_headers(authenticate_code, step_up_grant),
        )

    def update(
        self,
        treatment_id: int,
        treatment: Mapping[str, Any],
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Replace a treatment with the complete edited treatment object."""
        self._assert_belongs(treatment_id)
        return self._client.request(
            "PUT",
            f"{self.url}/{treatment_id}/update",
            json=self._update_body(treatment_id, treatment),
            headers=self._authentication_headers(authenticate_code, step_up_grant),
        )

    def activate(
        self,
        treatment_id: int,
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Activate a treatment — `PUT .../treatments/{t}/activate`."""
        self._assert_belongs(treatment_id)
        return self._client.request(
            "PUT",
            f"{self.url}/{treatment_id}/activate",
            headers=self._authentication_headers(authenticate_code, step_up_grant),
        )

    def deactivate(
        self,
        treatment_id: int,
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Deactivate a treatment — `PUT .../treatments/{t}/deactivate`."""
        self._assert_belongs(treatment_id)
        return self._client.request(
            "PUT",
            f"{self.url}/{treatment_id}/deactivate",
            headers=self._authentication_headers(authenticate_code, step_up_grant),
        )

    @staticmethod
    def _medicine_filter(
        medicine_id: int | None, medicine_family_id: int | None
    ) -> JSONDict | None:
        params: JSONDict = {}
        if medicine_id is not None:
            params["medicine_id"] = medicine_id
        if medicine_family_id is not None:
            params["medicine_family_id"] = medicine_family_id
        return params or None

    def check_medicine_ingredient_interactions(
        self,
        *,
        medicine_id: int | None = None,
        medicine_family_id: int | None = None,
    ) -> list[JSONDict]:
        """Check ingredient interactions for the patient's treatments."""
        self._scope_guard.ensure()
        return self._client.get(
            f"{self.url}/check-medicine-ingredient-interactions",
            params=self._medicine_filter(medicine_id, medicine_family_id),
        )

    def check_diagnoses_and_allergies(self) -> list[JSONDict]:
        """Return treatment conflicts with the patient's clinical rows."""
        self._scope_guard.ensure()
        return self._client.get(f"{self.url}/check-diagnoses-and-allergies")

    def check_medicine_ingredient_overdose(
        self,
        *,
        medicine_id: int | None = None,
        medicine_family_id: int | None = None,
    ) -> list[JSONDict]:
        """Check possible ingredient overdoses for medicine or family."""
        self._scope_guard.ensure()
        return self._client.get(
            f"{self.url}/check-medicine-ingredient-overdose",
            params=self._medicine_filter(medicine_id, medicine_family_id),
        )


class Treatment:
    """One treatment, including configuration, history and review actions."""

    def __init__(self, treatments: Treatments, treatment_id: int) -> None:
        self._treatments = treatments
        self._client = treatments._client
        self.id = treatment_id
        self._base_path = f"{treatments.url}/{treatment_id}"

    def _ensure_belongs(self) -> None:
        """Repeat the patient membership guard before an item action."""
        self._treatments._assert_belongs(self.id)

    def details(self) -> JSONDict:
        """Fetch the direct treatment object."""
        return self._treatments._checked_details(self.id)

    def with_configs(self) -> JSONDict:
        """Fetch the treatment together with editable schedule configs."""
        self._ensure_belongs()
        return self._client.get(f"{self._base_path}/with-configs")

    def treatment_config(self) -> list[JSONDict]:
        """Return the treatment's configuration rows."""
        self._ensure_belongs()
        return self._client.get(f"{self._base_path}/treatment-config")

    def search_historical(self, *, page: int = 1, items_per_page: int = 15) -> JSONDict:
        """Return one bounded page of the treatment's historical versions."""
        if page < 1 or items_per_page < 1:
            raise ValueError("page and items_per_page must be positive")
        self._ensure_belongs()
        return self._client.get(
            f"{self._base_path}/search-historical",
            params={"page": page, "itemsPerPage": items_per_page},
        )

    def update(
        self,
        treatment: Mapping[str, Any],
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Replace the treatment and its configs with the complete object."""
        self._ensure_belongs()
        return self._client.request(
            "PUT",
            f"{self._base_path}/update",
            json=self._treatments._update_body(self.id, treatment),
            headers=Treatments._authentication_headers(
                authenticate_code, step_up_grant
            ),
        )

    def activate(
        self,
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Activate this treatment."""
        self._ensure_belongs()
        return self._client.request(
            "PUT",
            f"{self._base_path}/activate",
            headers=Treatments._authentication_headers(
                authenticate_code, step_up_grant
            ),
        )

    def deactivate(
        self,
        *,
        authenticate_code: str | None = None,
        step_up_grant: str | None = None,
    ) -> Any:
        """Deactivate this treatment."""
        self._ensure_belongs()
        return self._client.request(
            "PUT",
            f"{self._base_path}/deactivate",
            headers=Treatments._authentication_headers(
                authenticate_code, step_up_grant
            ),
        )

    def review_approve(self) -> Any:
        """Approve this treatment in the pre-production review workflow."""
        self._ensure_belongs()
        return self._client.post(f"{self._base_path}/review-approve")

    def review_reject(self, *, reason: str) -> Any:
        """Reject this treatment in review and store the supplied reason."""
        self._ensure_belongs()
        return self._client.post(
            f"{self._base_path}/review-reject",
            json={"pre_production_review_rejected_reason": reason},
        )

    def __repr__(self) -> str:
        return f"Treatment(id={self.id})"


class _ClinicalRows(Resource):
    """Shared create/deactivate actions for allergy and diagnosis rows."""

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        super().__init__(client, base_path)
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)
        self.patient_id = self._scope_guard.patient_id

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Search rows, normalizing API-specific boolean `is_active` to 1/0."""
        self._scope_guard.ensure()
        if isinstance(filters.get("is_active"), bool):
            filters["is_active"] = int(filters["is_active"])
        return super().search(all_items=all_items, **filters)

    def _find(self, resource_id: int, *, refresh: bool = False) -> JSONDict:
        """Locate a clinical row across active and inactive scoped lists."""
        self._scope_guard.ensure(refresh=refresh)
        rows: list[JSONDict] = []
        for is_active in (1, 0):
            result = super().search(all_items=True, is_active=is_active)
            items = result.get("items")
            if not isinstance(items, list):
                raise TypeError("clinical search response has no items list")
            rows.extend(item for item in items if isinstance(item, dict))
        return _row_by_id(rows, resource_id, "clinical row")

    def get(self, resource_id: int) -> JSONDict:
        """Return a row from patient-scoped searches, never a guessed item GET."""
        return self._find(resource_id)

    def create(self, **fields: Any) -> Any:
        """Create a clinical row with the fields accepted by the API."""
        self._scope_guard.ensure(refresh=True)
        body = _scoped_body(fields, "patient_id", self.patient_id)
        return self._client.post(f"{self.url}/create", json=body)

    def deactivate(self, resource_id: int, payload: Mapping[str, Any]) -> Any:
        """Call the API's intentionally misspelled `deactive` action.

        The current SPA sends a body with `deactivate_reason` and `is_active`,
        but its handling of `is_active` is inconsistent. Requiring the raw
        mapping avoids pretending that an unverified boolean schema is stable.
        """
        self._find(resource_id, refresh=True)
        body = dict(payload)
        allowed = {"deactivate_reason", "is_active"}
        if set(body) != allowed:
            raise ValueError(
                "clinical deactivation requires only deactivate_reason and is_active"
            )
        return self._client.post(
            f"{self.url}/{resource_id}/deactive",
            json=body,
        )


class Allergies(_ClinicalRows):
    """Patient allergies — paginated `.../allergies/search` plus actions."""

    path = "allergies"


class Diagnoses(_ClinicalRows):
    """Patient diagnoses — paginated `.../diagnoses/search` plus actions."""

    path = "diagnoses"


class PatientDoctors(BareListResource):
    """Doctors assigned to a patient — a bare list with assignment actions."""

    path = "doctors"

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        super().__init__(client, base_path)
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)

    def list(self, **filters: Any) -> list[JSONDict]:
        """List assignments after validating the patient/center scope."""
        self._scope_guard.ensure()
        return super().list(**filters)

    def get(self, resource_id: int) -> JSONDict:
        """Return an assignment from the scoped bare list."""
        return _row_by_id(self.list(), resource_id, "doctor assignment")

    def _assert_assignment(self, association_id: int) -> None:
        """Repeat parent and association checks before a mutation."""
        self._scope_guard.ensure(refresh=True)
        rows = self._client.get(self.url)
        _row_by_id(rows, association_id, "doctor assignment")

    def _assert_doctor(self, doctor_id: int, specialization_id: int) -> None:
        """Require both selected ids to come from this center's lookups."""
        doctors = self._client.get(f"{self._scope_guard.center_path}/doctors")
        _row_by_id(doctors, doctor_id, "center doctor")
        specializations = self._client.get(
            f"{self._scope_guard.center_path}/doctors/specializations"
        )
        _row_by_id(specializations, specialization_id, "doctor specialization")

    @staticmethod
    def _assignment_body(doctor_id: int, doctor_specialization_id: int) -> JSONDict:
        return {
            "doctor_id": doctor_id,
            "doctor_specialization_id": doctor_specialization_id,
        }

    def assign(self, doctor_id: int, doctor_specialization_id: int) -> Any:
        """Assign a doctor — `POST .../assign-doctor`."""
        self._scope_guard.ensure(refresh=True)
        self._assert_doctor(doctor_id, doctor_specialization_id)
        return self._client.post(
            f"{self._base_path}/assign-doctor",
            json=self._assignment_body(doctor_id, doctor_specialization_id),
        )

    def update_assignment(
        self,
        association_id: int,
        doctor_id: int,
        doctor_specialization_id: int,
    ) -> Any:
        """Change one patient/doctor association."""
        self._assert_assignment(association_id)
        self._assert_doctor(doctor_id, doctor_specialization_id)
        return self._client.post(
            f"{self._base_path}/update-doctor/{association_id}",
            json=self._assignment_body(doctor_id, doctor_specialization_id),
        )

    def unassign(self, association_id: int) -> Any:
        """Remove one doctor assignment — `POST .../unassign-doctor/{id}`."""
        self._assert_assignment(association_id)
        return self._client.post(f"{self._base_path}/unassign-doctor/{association_id}")


class HolidayPeriods(DirectResource):
    """Patient holiday periods.

    The collection GET is direct (`.../holiday-periods`) but returns an
    `{"items": [...]}` envelope, so this uses `DirectResource`.
    """

    path = "holiday-periods"
    default_items_per_page = None

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        super().__init__(client, base_path)
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)
        self.patient_id = self._scope_guard.patient_id

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Return the direct envelope after validating the patient scope."""
        self._scope_guard.ensure()
        return super().search(all_items=all_items, **filters)

    def _find(self, period_id: int, *, refresh: bool = False) -> JSONDict:
        """Locate one period in the patient-scoped collection."""
        self._scope_guard.ensure(refresh=refresh)
        result = super().search(all_items=True)
        row = _row_by_id(result.get("items"), period_id, "holiday period")
        if row.get("patient_id") != self.patient_id:
            raise ValueError("holiday period does not belong to the scoped patient")
        return row

    def get(self, resource_id: int) -> JSONDict:
        """Return a period from the scoped collection."""
        return self._find(resource_id)

    def create(self, **fields: Any) -> Any:
        """Create a holiday period with the patient-form fields."""
        self._scope_guard.ensure(refresh=True)
        body = _scoped_body(fields, "patient_id", self.patient_id)
        return self._client.post(f"{self.url}/create", json=body)

    def update(self, period_id: int, period: Mapping[str, Any]) -> Any:
        """Replace a holiday period with its complete edited object."""
        self._find(period_id, refresh=True)
        body = _scoped_body(period, "id", period_id)
        body = _scoped_body(body, "patient_id", self.patient_id)
        return self._client.request("PUT", f"{self.url}/{period_id}/update", json=body)

    def delete(self, period_id: int) -> Any:
        """Delete a holiday period — `DELETE .../{id}/delete`."""
        self._find(period_id, refresh=True)
        return self._client.request("DELETE", f"{self.url}/{period_id}/delete")


class HospitalizationPeriods(Resource):
    """Patient hospitalization periods (`.../search` plus write actions)."""

    path = "hospitalization-periods"

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        super().__init__(client, base_path)
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)
        self.patient_id = self._scope_guard.patient_id

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Search periods after validating the patient scope."""
        self._scope_guard.ensure()
        return super().search(all_items=all_items, **filters)

    def _find(self, period_id: int, *, refresh: bool = False) -> JSONDict:
        """Locate one period in the patient-scoped search."""
        self._scope_guard.ensure(refresh=refresh)
        result = super().search(all_items=True)
        return _row_by_id(result.get("items"), period_id, "hospitalization period")

    def get(self, resource_id: int) -> JSONDict:
        """Return a period from the scoped search."""
        return self._find(resource_id)

    def create(self, **fields: Any) -> Any:
        """Create a hospitalization period."""
        self._scope_guard.ensure(refresh=True)
        body = _scoped_body(fields, "patient_id", self.patient_id, inject=False)
        return self._client.post(f"{self.url}/create", json=body)

    def update(self, period_id: int, period: Mapping[str, Any]) -> Any:
        """Replace a hospitalization period with its complete object."""
        self._find(period_id, refresh=True)
        body = _scoped_body(period, "id", period_id)
        body = _scoped_body(body, "patient_id", self.patient_id, inject=False)
        return self._client.request("PUT", f"{self.url}/{period_id}/update", json=body)

    def deactivate(self, period_id: int) -> Any:
        """Deactivate a hospitalization period — `PUT .../{id}/deactivate`."""
        self._find(period_id, refresh=True)
        return self._client.request("PUT", f"{self.url}/{period_id}/deactivate")


class Attachments:
    """Patient attachments, including multipart upload and binary download.

    `search()` returns the API's `{"data": [...]}` envelope rather than the
    usual `items` shape. File values use httpx's `files=` format: an open binary
    file, bytes, or a `(filename, file, content_type)` tuple.
    """

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        self._client = client
        self._base_path = base_path
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)

    @property
    def url(self) -> str:
        """Path of the attachment collection."""
        return f"{self._base_path}/attachments"

    def search(self, **filters: Any) -> JSONDict:
        """Return `GET .../attachments/search` without changing its envelope."""
        self._scope_guard.ensure()
        return self._client.get(f"{self.url}/search", params=filters or None)

    def list(self, **filters: Any) -> list[JSONDict]:
        """Return only the attachment rows from the API's `data` envelope."""
        return self.search(**filters)["data"]

    def get(self, attachment_id: int) -> JSONDict:
        """Return attachment metadata from the patient-scoped search."""
        return _row_by_id(self.list(), attachment_id, "attachment")

    def _assert_belongs(self, attachment_id: int, *, refresh: bool) -> None:
        """Repeat parent and attachment-list checks before an item request."""
        self._scope_guard.ensure(refresh=refresh)
        result = self._client.get(f"{self.url}/search")
        if not isinstance(result, dict):
            raise TypeError("attachment search response is not an object")
        _row_by_id(result.get("data"), attachment_id, "attachment")

    def create(self, *, file: Any, title: str) -> Any:
        """Upload an attachment as multipart form data."""
        self._scope_guard.ensure(refresh=True)
        return self._client.post(
            f"{self.url}/create",
            data={"title": title},
            files={"file": file},
        )

    def download(self, attachment_id: int) -> bytes:
        """Download an attachment without attempting to decode it as JSON."""
        self._assert_belongs(attachment_id, refresh=False)
        return self._client.get_bytes(f"{self.url}/{attachment_id}/download")

    def update(self, attachment_id: int, *, title: str) -> Any:
        """Rename an attachment — `PUT .../{id}/update`."""
        self._assert_belongs(attachment_id, refresh=True)
        return self._client.request(
            "PUT", f"{self.url}/{attachment_id}/update", json={"title": title}
        )

    def delete(self, attachment_id: int) -> Any:
        """Delete an attachment — `DELETE .../{id}/delete`."""
        self._assert_belongs(attachment_id, refresh=True)
        return self._client.request("DELETE", f"{self.url}/{attachment_id}/delete")

    def __repr__(self) -> str:
        return f"Attachments(url={self.url!r})"


class Sales(DirectResource):
    """Patient sales — direct paginated GET at `.../patients/{p}/sales`.

    Confirmed filters include `itemsPerPage`, `page` and `query`; table-specific
    filters are passed through unchanged.
    """

    path = "sales"

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        super().__init__(client, base_path)
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)

    def search(self, *, all_items: bool = True, **filters: Any) -> JSONDict:
        """Search sales only after validating the patient/center scope."""
        self._scope_guard.ensure()
        return super().search(all_items=all_items, **filters)

    def get(self, resource_id: int) -> JSONDict:
        """Disable the unobserved direct sale-item route."""
        raise NotImplementedError(
            "patient sales expose only the verified collection endpoint"
        )


class SaleProgramCodes:
    """Medication-provider program codes associated with one patient."""

    def __init__(
        self,
        client: "AmcoClient",
        base_path: str,
        patient_id: int,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        self._client = client
        self._base_path = f"{base_path}/sale-program-codes"
        self._patient_id = patient_id
        self._scope_guard = scope_guard or _PatientScopeGuard(client, base_path)

    @property
    def url(self) -> str:
        """Base path used by the code actions."""
        return self._base_path

    def list(self) -> list[JSONDict]:
        """Return the bare list from `GET .../sale-program-codes/list`."""
        self._scope_guard.ensure()
        return self._client.get(f"{self.url}/list")

    def get(self, code_id: int) -> JSONDict:
        """Return a program code from the patient-scoped list."""
        return _row_by_id(self.list(), code_id, "sale program code")

    def _assert_belongs(self, code_id: int) -> None:
        """Repeat parent and code-list checks before a mutation."""
        self._scope_guard.ensure(refresh=True)
        rows = self._client.get(f"{self.url}/list")
        row = _row_by_id(rows, code_id, "sale program code")
        supplied_patient_id = row.get("patient_id")
        if supplied_patient_id is not None and supplied_patient_id != self._patient_id:
            raise ValueError("sale program code does not belong to the scoped patient")

    def create(self, *, medication_provider_id: int, code: str) -> Any:
        """Create a patient program code."""
        self._scope_guard.ensure(refresh=True)
        return self._client.post(
            f"{self.url}/create",
            json={
                "patient_id": self._patient_id,
                "medication_provider_id": medication_provider_id,
                "code": code,
                "id": None,
            },
        )

    def update(self, code_id: int, record: Mapping[str, Any]) -> Any:
        """Replace a program code with the complete edited record."""
        self._assert_belongs(code_id)
        body = _scoped_body(record, "id", code_id)
        body = _scoped_body(body, "patient_id", self._patient_id)
        return self._client.request("PUT", f"{self.url}/{code_id}/update", json=body)

    def delete(self, code_id: int) -> Any:
        """Delete a program code — `DELETE .../{id}/delete`."""
        self._assert_belongs(code_id)
        return self._client.request("DELETE", f"{self.url}/{code_id}/delete")

    def __repr__(self) -> str:
        return f"SaleProgramCodes(url={self.url!r})"


class _DoseTakesSnapshot(dict[str, Any]):
    """Sensitive control response carrying its originating scope token."""

    def __init__(self, data: Mapping[str, Any], owner: object) -> None:
        super().__init__(data)
        self._owner = owner
        patient_proofs: set[tuple[int, int]] = set()
        for key in (
            "patient_dose_takes_without_production_dose_take",
            "patient_dose_takes_with_production_dose_take",
        ):
            rows = data.get(key)
            if not isinstance(rows, list):
                raise TypeError("dose-take control response has an invalid array")
            for row in rows:
                if not isinstance(row, Mapping):
                    raise TypeError("dose-take control array contains a non-object")
                row_id = row.get("id")
                patient_id = row.get("patient_id")
                if (
                    isinstance(row_id, int)
                    and not isinstance(row_id, bool)
                    and isinstance(patient_id, int)
                    and not isinstance(patient_id, bool)
                ):
                    patient_proofs.add((row_id, patient_id))

        production_rows = data.get("production_dose_takes_without_patient_dose_take")
        if not isinstance(production_rows, list):
            raise TypeError("dose-take control response has an invalid array")
        production_proofs: set[tuple[int, int]] = set()
        for row in production_rows:
            if not isinstance(row, Mapping):
                raise TypeError("dose-take control array contains a non-object")
            row_id = row.get("id")
            production_id = row.get("production_id")
            if (
                isinstance(row_id, int)
                and not isinstance(row_id, bool)
                and isinstance(production_id, int)
                and not isinstance(production_id, bool)
            ):
                production_proofs.add((row_id, production_id))

        self._patient_proofs = frozenset(patient_proofs)
        self._production_proofs = frozenset(production_proofs)

    def __repr__(self) -> str:
        keys = sorted(key for key in self if isinstance(key, str))
        return f"DoseTakesSnapshot(keys={keys!r})"

    __str__ = __repr__


class DoseTakesControl:
    """Dose-administration rows shown by the patient's TAKES tab.

    This is deliberately named `dose_takes`, not `intakes`: center intake
    association/grouping resources configure time slots, while these endpoints
    represent actual medication administrations. Marking or rejecting a row and
    running `simulate()` are real, auditable actions.
    """

    def __init__(
        self,
        client: "AmcoClient",
        patient_path: str,
        installation_path: str,
        patient_id: int,
        scope_guard: _PatientScopeGuard | None = None,
    ) -> None:
        self._client = client
        self._patient_path = patient_path
        self._installation_path = installation_path
        self._patient_id = patient_id
        self._scope_guard = scope_guard or _PatientScopeGuard(client, patient_path)
        self._snapshot_owner = object()

    @property
    def url(self) -> str:
        """Path of the patient dose-take control endpoint."""
        return f"{self._patient_path}/dose-takes-control"

    def search(
        self,
        *,
        date_at: str | date,
        page: int = 1,
        items_per_page: int = 15,
        is_active: bool | None = None,
        query: str | None = None,
    ) -> JSONDict:
        """Return one dated page of patient and production dose-take rows.

        The response is a custom object with three arrays: unmatched patient
        takes, matched patient/production takes and unmatched production takes.
        """
        if page < 1 or items_per_page < 1:
            raise ValueError("page and items_per_page must be positive")
        params: JSONDict = {
            "date_at": date_at.isoformat() if isinstance(date_at, date) else date_at,
            "page": page,
            "itemsPerPage": items_per_page,
        }
        if is_active is not None:
            params["is_active"] = is_active
        if query is not None:
            params["query"] = query
        self._scope_guard.ensure()
        response = self._client.get(self.url, params=params)
        if not isinstance(response, Mapping):
            raise TypeError("dose-take control response is not an object")
        return _DoseTakesSnapshot(response, self._snapshot_owner)

    def for_bag(
        self,
        bag_id: str | int,
        *,
        allow_unverified_scope: bool = False,
    ) -> JSONDict:
        """Return one bag's rows after an explicit ownership-risk opt-in.

        The endpoint offers no patient-scoped bag lookup with which the SDK can
        prove that an arbitrary scanner id belongs to this patient. Callers
        must derive it from trusted workflow state and opt in explicitly.
        """
        if not allow_unverified_scope:
            raise ValueError(
                "bag lookup requires allow_unverified_scope=True and a trusted id"
            )
        bag_segment = quote(str(bag_id).strip(), safe="")
        if not bag_segment:
            raise ValueError("bag_id must not be empty")
        self._scope_guard.ensure()
        response = self._client.get(
            f"{self._patient_path}/bags/{bag_segment}/dose-takes-control"
        )
        if not isinstance(response, Mapping):
            raise TypeError("dose-take control response is not an object")
        return _DoseTakesSnapshot(response, self._snapshot_owner)

    def simulate(self) -> Any:
        """Run the patient's take simulation — a mutating POST action."""
        self._scope_guard.ensure(refresh=True)
        return self._client.post(f"{self._patient_path}/takes-simulate")

    def _assert_patient_take(
        self,
        dose_take_id: int,
        control: Mapping[str, Any],
    ) -> None:
        """Require a positive match in a patient-scoped control response."""
        snapshot = self._checked_snapshot(control)
        self._scope_guard.ensure(refresh=True)
        if (dose_take_id, self._patient_id) not in snapshot._patient_proofs:
            raise ValueError("dose take does not belong to the scoped patient")

    def _assert_production_take(
        self,
        production_id: int,
        dose_take_id: int,
        control: Mapping[str, Any],
    ) -> None:
        """Require a positive match in a scoped production-only array."""
        snapshot = self._checked_snapshot(control)
        self._scope_guard.ensure(refresh=True)
        if (dose_take_id, production_id) not in snapshot._production_proofs:
            raise ValueError("dose take does not belong to the scoped production")

    def _checked_snapshot(self, control: Mapping[str, Any]) -> _DoseTakesSnapshot:
        """Accept only a control response loaded by this patient scope."""
        if not isinstance(control, _DoseTakesSnapshot) or (
            control._owner is not self._snapshot_owner
        ):
            raise ValueError(
                "control must be returned by this dose_takes search or bag lookup"
            )
        return control

    def mark_taken(
        self,
        dose_take_id: int,
        *,
        control: Mapping[str, Any],
    ) -> Any:
        """Mark a patient dose take found in a prior scoped control response."""
        self._assert_patient_take(dose_take_id, control)
        return self._client.post(
            f"{self._patient_path}/patient-dose-takes/{dose_take_id}/mark-taken"
        )

    def mark_rejected(
        self,
        dose_take_id: int,
        *,
        control: Mapping[str, Any],
        reason: str,
    ) -> Any:
        """Reject a patient dose take found in a scoped control response."""
        self._assert_patient_take(dose_take_id, control)
        return self._client.post(
            f"{self._patient_path}/patient-dose-takes/{dose_take_id}/mark-rejected",
            json={"reason": reason},
        )

    def production_patient(
        self,
        production_id: int,
        *,
        allow_unverified_scope: bool = False,
    ) -> Any:
        """Return production rows after an explicit ownership-risk opt-in.

        No independently scoped production-row lookup is available to prove
        that an arbitrary production id belongs with this patient.
        """
        if not allow_unverified_scope:
            raise ValueError(
                "production lookup requires allow_unverified_scope=True and "
                "a trusted id"
            )
        self._scope_guard.ensure()
        return self._client.get(
            f"{self._installation_path}/productions/{production_id}"
            f"/patients/{self._patient_id}/dose-takes"
        )

    def mark_production_taken(
        self,
        production_id: int,
        dose_take_id: int,
        *,
        control: Mapping[str, Any],
        allow_unverified_scope: bool = False,
    ) -> Any:
        """Mark a production take after a positive, explicit-risk preflight."""
        if not allow_unverified_scope:
            raise ValueError("production action requires allow_unverified_scope=True")
        self._assert_production_take(production_id, dose_take_id, control)
        return self._client.post(
            f"{self._installation_path}/productions/{production_id}"
            f"/dose-takes/{dose_take_id}/mark-taken"
        )

    def mark_production_rejected(
        self,
        production_id: int,
        dose_take_id: int,
        *,
        control: Mapping[str, Any],
        reason: str,
        allow_unverified_scope: bool = False,
    ) -> Any:
        """Reject a production take after a positive, explicit-risk preflight."""
        if not allow_unverified_scope:
            raise ValueError("production action requires allow_unverified_scope=True")
        self._assert_production_take(production_id, dose_take_id, control)
        return self._client.post(
            f"{self._installation_path}/productions/{production_id}"
            f"/dose-takes/{dose_take_id}/mark-rejected",
            json={"reason": reason},
        )

    def __repr__(self) -> str:
        return f"DoseTakesControl(url={self.url!r})"


class Patient:
    """One patient and the resources exposed by their record tabs.

    Build this scope with `center.patient(id)`. Construction performs no I/O.
    Its responses can contain identity, contact, clinical, medication and sales
    information; treat every returned dictionary as sensitive.
    """

    def __init__(self, client: "AmcoClient", base_path: str, patient_id: int) -> None:
        self._client = client
        self.id = patient_id
        self._base_path = f"{base_path}/patients/{patient_id}"
        installation_path = base_path.partition("/centers/")[0]
        self._scope_guard = _PatientScopeGuard(client, self._base_path)

        self.treatments = Treatments(client, self._base_path, self._scope_guard)
        self.allergies = Allergies(client, self._base_path, self._scope_guard)
        self.diagnoses = Diagnoses(client, self._base_path, self._scope_guard)
        self.doctors = PatientDoctors(client, self._base_path, self._scope_guard)
        self.holiday_periods = HolidayPeriods(
            client, self._base_path, self._scope_guard
        )
        self.hospitalization_periods = HospitalizationPeriods(
            client, self._base_path, self._scope_guard
        )
        self.attachments = Attachments(client, self._base_path, self._scope_guard)
        self.sales = Sales(client, self._base_path, self._scope_guard)
        self.sale_program_codes = SaleProgramCodes(
            client, self._base_path, patient_id, self._scope_guard
        )
        self.dose_takes = DoseTakesControl(
            client,
            self._base_path,
            installation_path,
            patient_id,
            self._scope_guard,
        )

    def details(self) -> JSONDict:
        """Fetch the complete patient record — `GET .../patients/{p}`."""
        return self._scope_guard.details(refresh=True)

    def update(self, patient: Mapping[str, Any]) -> Any:
        """Replace the patient form record — `PUT .../patients/{p}/update`.

        The web client sends the complete object returned by `details()`, with
        the edited fields applied. Partial-update semantics have not been
        established, so this method deliberately requires an explicit mapping.
        """
        self._scope_guard.ensure(refresh=True)
        body = _scoped_body(patient, "id", self.id)
        body = _scoped_body(body, "center_id", self._scope_guard.center_id)
        if body.get("login") == "" and body.get("password") == "":
            body.pop("login")
            body.pop("password")
        return self._client.request("PUT", f"{self._base_path}/update", json=body)

    def activate(self) -> Any:
        """Activate this patient — `PUT .../patients/{p}/activate`."""
        self._scope_guard.ensure(refresh=True)
        return self._client.request("PUT", f"{self._base_path}/activate")

    def deactivate(self) -> Any:
        """Deactivate this patient — `PUT .../patients/{p}/deactivate`."""
        self._scope_guard.ensure(refresh=True)
        return self._client.request("PUT", f"{self._base_path}/deactivate")

    def set_image(self, image: Any) -> Any:
        """Upload the patient image as multipart field `image`.

        Pass an open binary file, bytes, or an httpx-compatible file tuple.
        """
        self._scope_guard.ensure(refresh=True)
        return self._client.post(
            f"{self._base_path}/set-image-patient", files={"image": image}
        )

    def electronic_prescription(self) -> Any:
        """Return the Amco+ electronic-prescription handoff data.

        The browser subsequently submits that data to an external provider;
        this method performs only the Amco+ GET and never makes the external
        POST.
        """
        self._scope_guard.ensure()
        return self._client.get(f"{self._base_path}/electronic-prescription")

    def treatment(self, treatment_id: int) -> Treatment:
        """Return a treatment scope without making a request.

        Each read or mutation checks the detail response's `patient_id` before
        returning it or issuing a subsequent action request.
        """
        return Treatment(self.treatments, treatment_id)

    def __repr__(self) -> str:
        return f"Patient(id={self.id})"
