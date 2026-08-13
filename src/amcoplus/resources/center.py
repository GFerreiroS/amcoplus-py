"""Center (residence) scope, its patients, and per-patient resources."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .base import Resource

if TYPE_CHECKING:
    from ..client import AmcoClient


class Patients(Resource):
    path = "patients"


class Treatments(Resource):
    path = "treatments"


class Center:
    """A residence served by an installation. Patient-level resources live here."""

    def __init__(self, client: "AmcoClient", base_path: str, center_id: int):
        self._client = client
        self.id = center_id
        self._base_path = f"{base_path}/centers/{center_id}"

        self.patients = Patients(client, self._base_path)

    def patient(self, patient_id: int) -> "Patient":
        """Return a Patient scoped to this center."""
        return Patient(self._client, self._base_path, patient_id)

    def __repr__(self) -> str:
        return f"Center(id={self.id})"


class Patient:
    """A single patient. Treatment-level resources hang off here."""

    def __init__(self, client: "AmcoClient", base_path: str, patient_id: int):
        self._client = client
        self.id = patient_id
        self._base_path = f"{base_path}/patients/{patient_id}"

        self.treatments = Treatments(client, self._base_path)

    def __repr__(self) -> str:
        return f"Patient(id={self.id})"
