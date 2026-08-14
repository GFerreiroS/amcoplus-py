"""Privacy-conscious, read-only examples for every implemented patient tab.

Every API call after authentication is a GET. Responses can contain identity,
clinical, medication, sales and administration data, so this script prints only
counts, a small preview of internal IDs and field names. It never follows the
external electronic-prescription URL and never exposes mobile alerts.

Usage:
    python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID --patients
    python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
        --patient-id PATIENT_ID --card --clinical --treatments
    python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
        --patient-id PATIENT_ID --sales
    python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
        --patient-id PATIENT_ID --takes-date YYYY-MM-DD
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Callable, Mapping
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from amcoplus import AmcoClient, AmcoError, Patient

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ID_PREVIEW_SIZE = 10


def positive_int(value: str) -> int:
    """Parse a positive integer for IDs and page numbers."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def iso_date(value: str) -> date:
    """Parse one ISO calendar date without accepting a date range."""
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be YYYY-MM-DD") from exc


def parse_args() -> argparse.Namespace:
    """Read the scope and explicitly selected read-only sections."""
    parser = argparse.ArgumentParser(
        description=(
            "Inspect privacy-conscious patient-tab responses without printing values."
        ),
        epilog=(
            "Examples:\n"
            "  python scripts/patients_and_treatments.py "
            "INSTALLATION_ID CENTER_ID --patients\n"
            "  python scripts/patients_and_treatments.py "
            "INSTALLATION_ID CENTER_ID --patient-id PATIENT_ID "
            "--card --clinical\n"
            "  python scripts/patients_and_treatments.py "
            "INSTALLATION_ID CENTER_ID --patient-id PATIENT_ID --sales\n"
            "  python scripts/patients_and_treatments.py "
            "INSTALLATION_ID CENTER_ID --patient-id PATIENT_ID "
            "--takes-date YYYY-MM-DD"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("installation_id", type=positive_int)
    parser.add_argument("center_id", type=positive_int)
    parser.add_argument("--patient-id", type=positive_int)
    parser.add_argument("--treatment-id", type=positive_int)
    parser.add_argument("--page", type=positive_int, default=1)
    parser.add_argument("--treatment-page", type=positive_int)
    parser.add_argument(
        "--include-inactive",
        action="store_true",
        help="Do not restrict the center patient search to active patients.",
    )
    parser.add_argument(
        "--patients",
        action="store_true",
        help="Inspect one bounded center patient page.",
    )
    parser.add_argument(
        "--card",
        action="store_true",
        help="Inspect Information-tab response shapes.",
    )
    parser.add_argument(
        "--clinical",
        action="store_true",
        help="Inspect one page of diagnoses and allergies.",
    )
    parser.add_argument(
        "--sales",
        action="store_true",
        help="Inspect one page of sales and the program-code count.",
    )
    parser.add_argument(
        "--treatments",
        action="store_true",
        help="Inspect one treatment page and the medical-order shape.",
    )
    parser.add_argument(
        "--treatment-checks",
        action="store_true",
        help="Count the three read-only clinical checks used by the editor.",
    )
    parser.add_argument(
        "--takes-date",
        type=iso_date,
        help="Inspect dose administrations for one exact YYYY-MM-DD date.",
    )
    parser.add_argument(
        "--lookups",
        action="store_true",
        help="Count allowed patient and treatment form lookups.",
    )
    args = parser.parse_args()

    patient_options = (
        args.card,
        args.clinical,
        args.sales,
        args.treatments,
        args.treatment_checks,
        args.takes_date is not None,
        args.treatment_id is not None,
        args.treatment_page is not None,
    )
    if any(patient_options) and args.patient_id is None:
        parser.error("patient sections require --patient-id")
    if args.treatment_id is not None:
        args.treatments = True
    if args.treatment_page is not None:
        args.treatments = True
    if args.include_inactive and not args.patients:
        parser.error("--include-inactive requires --patients")
    if not (args.patients or any(patient_options) or args.lookups):
        parser.error("select --patients, a patient section, or --lookups")
    return args


def build_client() -> AmcoClient:
    """Build a client from credentials supplied by the environment or `.env`."""
    load_dotenv(PROJECT_ROOT / ".env")
    try:
        login = os.environ["AMCO_LOGIN"]
        password = os.environ["AMCO_PASSWORD"]
    except KeyError as exc:
        raise SystemExit(
            f"Missing {exc.args[0]} in the environment or {PROJECT_ROOT / '.env'}"
        ) from None

    base_url = os.getenv("AMCO_BASE_URL")
    if base_url:
        return AmcoClient(login=login, password=password, base_url=base_url)
    return AmcoClient(login=login, password=password)


def resource_id(item: dict[str, Any]) -> int | None:
    """Return an integer resource ID without assuming every row has one."""
    value = item.get("id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def show_ids(items: list[dict[str, Any]]) -> None:
    """Print a bounded preview of internal IDs, never full rows."""
    ids = [item_id for item in items if (item_id := resource_id(item)) is not None]
    if not ids:
        return
    preview = ", ".join(str(item_id) for item_id in ids[:ID_PREVIEW_SIZE])
    suffix = ", ..." if len(ids) > ID_PREVIEW_SIZE else ""
    print(f"  IDs: {preview}{suffix}")


def show_items(label: str, items: Any, total: Any = None) -> None:
    """Print a count and optional internal-ID preview."""
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{label} response is not a list of objects")
    if isinstance(total, int) and not isinstance(total, bool) and total < 0:
        print(f"{label}: total unavailable (fetched {len(items)} rows)")
        show_ids(items)
        return
    total = (
        total if isinstance(total, int) and not isinstance(total, bool) else len(items)
    )
    print(f"{label}: {total} total (fetched {len(items)} rows)")
    show_ids(items)


def show_search_page(label: str, result: Any) -> None:
    """Print a standard `items` pagination envelope safely."""
    if not isinstance(result, Mapping):
        raise TypeError(f"{label} response is not an object")
    items = result.get("items")
    if not isinstance(items, list):
        raise TypeError(f"{label} response has no items list")
    total = result.get("maxResults", result.get("max_results"))
    show_items(label, items, total)


def show_data(label: str, result: Any) -> None:
    """Print the attachment API's `data` list safely."""
    if not isinstance(result, Mapping):
        raise TypeError(f"{label} response is not an object")
    items = result.get("data")
    if not isinstance(items, list):
        raise TypeError(f"{label} response has no data list")
    show_items(label, items)


def show_fields(label: str, details: Any) -> None:
    """Print only field names from one sensitive record."""
    if not isinstance(details, Mapping) or not all(
        isinstance(key, str) for key in details
    ):
        raise TypeError(f"{label} response is not an object with string keys")
    print(f"{label} fields ({len(details)}): {', '.join(sorted(details))}")


def show_custom_lists(label: str, result: Any) -> None:
    """Print only keys and lengths from a custom object of arrays."""
    if not isinstance(result, Mapping) or not all(
        isinstance(key, str) for key in result
    ):
        raise TypeError(f"{label} response is not an object with string keys")
    print(f"{label}:")
    for key in sorted(result):
        value = result[key]
        if isinstance(value, list):
            print(f"  {key}: {len(value)} rows")


def show_patient_card(patient: Patient) -> None:
    """Inspect the Information tab without exposing its values."""
    show_fields("Patient detail", patient.details())
    show_items("Assigned doctors", patient.doctors.list())
    show_search_page(
        "Holiday periods",
        patient.holiday_periods.search(page=1, itemsPerPage=15),
    )
    show_search_page(
        "Hospitalization periods",
        patient.hospitalization_periods.search(all_items=False, page=1),
    )
    show_data("Attachments", patient.attachments.search())
    show_fields("Electronic prescription", patient.electronic_prescription())


def show_clinical(patient: Patient, page: int) -> None:
    """Inspect bounded allergy and diagnosis pages."""
    filters = {"all_items": False, "page": page, "is_active": True}
    show_search_page("Diagnoses", patient.diagnoses.search(**filters))
    show_search_page("Allergies", patient.allergies.search(**filters))


def show_sales(patient: Patient, page: int) -> None:
    """Inspect a bounded sales page and bare program-code list."""
    show_search_page("Sales", patient.sales.search(all_items=False, page=page))
    show_items("Sale program codes", patient.sale_program_codes.list())


def show_treatments(patient: Patient, page: int, treatment_id: int | None) -> None:
    """Inspect treatment list, medical order and optional treatment detail."""
    treatment_page = patient.treatments.search(all_items=False, page=page)
    show_search_page("Treatments", treatment_page)
    medical_order = patient.treatments.medical_order()
    show_fields("Medical order", medical_order)
    lines = medical_order.get("medical_order_lines")
    if isinstance(lines, list):
        print(f"Medical-order lines: {len(lines)} rows")

    if treatment_id is None:
        return
    items = treatment_page.get("items")
    if not isinstance(items, list) or not any(
        isinstance(item, dict) and item.get("id") == treatment_id for item in items
    ):
        raise ValueError(
            "--treatment-id must come from the selected page of this patient"
        )
    treatment = patient.treatment(treatment_id)
    show_fields("Treatment detail", treatment.details())
    show_fields("Treatment with configs", treatment.with_configs())
    show_items("Treatment configs", treatment.treatment_config())
    show_search_page(
        "Treatment history",
        treatment.search_historical(page=page, items_per_page=15),
    )


def show_treatment_checks(patient: Patient) -> None:
    """Count the editor's clinical checks without printing their contents."""
    show_items(
        "Ingredient interactions",
        patient.treatments.check_medicine_ingredient_interactions(),
    )
    show_items(
        "Diagnosis/allergy conflicts",
        patient.treatments.check_diagnoses_and_allergies(),
    )
    show_items(
        "Possible overdoses",
        patient.treatments.check_medicine_ingredient_overdose(),
    )


def show_lookups(client: AmcoClient, installation_id: int, center_id: int) -> None:
    """Count the allowed dictionaries loaded by patient/treatment forms."""
    installation = client.installation(installation_id)
    center = installation.center(center_id)
    bare: list[tuple[str, Callable[[], list[dict[str, Any]]]]] = [
        ("Countries", client.root.countries.list),
        ("Genders", client.root.genders.list),
        ("Functional units", client.root.functional_units.list),
        ("Allergy catalog", client.root.allergies.list),
        ("Diagnosis catalog", client.root.diagnoses.list),
        ("Diagnosis types", client.root.diagnose_types.list),
        ("Dysphagia textures", client.root.dysphagia_textures.list),
        ("Lab units", client.root.lab_units.list),
        ("Treatment plans", client.root.treatment_plans.list),
        ("Administration routes", installation.administration_routes.list),
        ("Medication providers", installation.medication_providers.list),
        ("Center doctors", center.doctors.list),
        ("Doctor specializations", center.doctors.specializations),
        ("Center modules", center.modules.list),
        ("Center intake times", center.intakes_association.list),
    ]
    for label, load in bare:
        show_items(label, load())
    show_search_page("Holiday reasons", installation.holiday_reasons.search())
    show_search_page(
        "Hospitalization motivations",
        installation.hospitalization_motivations.search(all_items=False, page=1),
    )
    show_search_page(
        "Medicine ingredients",
        client.root.medicine_ingredients.search(all_items=False, page=1, query=""),
    )
    show_search_page(
        "ICD diagnoses",
        client.root.international_classification_diseases.search(
            all_items=False, page=1, query=""
        ),
    )
    show_search_page(
        "Medicines",
        installation.medicines.search(
            all_items=False,
            page=1,
            query="",
            with_count=False,
        ),
    )
    show_search_page(
        "Medicine-family levels",
        installation.medicine_family_levels.search(all_items=False, page=1),
    )
    show_search_page(
        "Medicine families",
        installation.medicine_families.search(all_items=False, page=1, query=""),
    )


def safe_error(exc: AmcoError) -> str:
    """Describe an API error without echoing server message/details."""
    parts = [type(exc).__name__]
    if exc.error_code is not None:
        parts.append(f"error_code={exc.error_code}")
    if exc.log_correlation_id:
        parts.append(f"log_correlation_id={exc.log_correlation_id}")
    return ", ".join(parts)


def main() -> None:
    """Run only the explicitly requested read-only sections."""
    args = parse_args()
    client = build_client()
    center = client.installation(args.installation_id).center(args.center_id)

    try:
        if args.patients:
            filters: dict[str, Any] = {}
            if not args.include_inactive:
                filters["is_active"] = True
            result = center.patients.search(
                all_items=False,
                page=args.page,
                **filters,
            )
            show_search_page("Patients", result)
        if args.patient_id is not None:
            patient = center.patient(args.patient_id)
            if args.card:
                show_patient_card(patient)
            if args.clinical:
                show_clinical(patient, args.page)
            if args.sales:
                show_sales(patient, args.page)
            if args.treatments:
                show_treatments(patient, args.treatment_page or 1, args.treatment_id)
            if args.treatment_checks:
                show_treatment_checks(patient)
            if args.takes_date is not None:
                show_custom_lists(
                    "Dose takes",
                    patient.dose_takes.search(
                        date_at=args.takes_date,
                        page=args.page,
                        is_active=True,
                    ),
                )
        if args.lookups:
            show_lookups(client, args.installation_id, args.center_id)
    except AmcoError as exc:
        raise SystemExit(f"Amco+ request failed ({safe_error(exc)})") from None
    except ValueError:
        raise SystemExit("Invalid scoped selection") from None
    except (KeyError, TypeError):
        raise SystemExit("Unexpected Amco+ response shape") from None


if __name__ == "__main__":
    main()
