"""Center (residence) scope, its patients, and per-patient resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Resource

if TYPE_CHECKING:
    from ..client import AmcoClient

__all__ = ["Center", "Patient", "Patients", "Treatments"]


class Patients(Resource):
    """Patients of a center — `/installations/{i}/centers/{c}/patients/search`.

    Filters:
        is_active (bool): Only active patients.
        query (str): Free-text search.
    """

    path = "patients"


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

    Example:
        ```python
        center = client.installation(65).center(417)
        for patient in center.patients.list(is_active=True):
            print(patient["id"])
        ```
    """

    def __init__(self, client: "AmcoClient", base_path: str, center_id: int) -> None:
        self._client = client
        self.id = center_id
        self._base_path = f"{base_path}/centers/{center_id}"

        self.patients = Patients(client, self._base_path)

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
