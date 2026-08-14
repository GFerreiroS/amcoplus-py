"""Read-only examples for installation and center resources.

Apart from the login request, every API call in the examples is a GET. API
responses may contain personal or clinical data, so the output is limited to
counts, IDs and field names.

Usage:
    python scripts/centers.py INSTALLATION_ID
    python scripts/centers.py INSTALLATION_ID --configuration-lookups
    python scripts/centers.py INSTALLATION_ID --center-id CENTER_ID
    python scripts/centers.py INSTALLATION_ID --center-id CENTER_ID \
        --resources --patient-id PATIENT_ID --module-id MODULE_ID

Data-changing calls are deliberately absent from this read-only script.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from amcoplus import AmcoClient, AmcoError, Center, Installation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ID_PREVIEW_SIZE = 10


def positive_int(value: str) -> int:
    """Parse a strictly positive resource id."""
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args() -> argparse.Namespace:
    """Read the installation and optional nested resource IDs."""
    parser = argparse.ArgumentParser(
        description="Run safe, read-only examples for Amco+ centers.",
        epilog=(
            "Examples:\n"
            "  python scripts/centers.py INSTALLATION_ID\n"
            "  python scripts/centers.py INSTALLATION_ID "
            "--configuration-lookups\n"
            "  python scripts/centers.py INSTALLATION_ID "
            "--center-id CENTER_ID\n"
            "  python scripts/centers.py INSTALLATION_ID "
            "--center-id CENTER_ID --resources\n"
            "  python scripts/centers.py INSTALLATION_ID "
            "--center-id CENTER_ID --patient-id PATIENT_ID "
            "--module-id MODULE_ID --medicine-id MEDICINE_ID"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "installation_id",
        type=positive_int,
        help="Installation whose centers will be listed.",
    )
    parser.add_argument(
        "--center-id",
        type=positive_int,
        help="Also show the field names of this center's detail.",
    )
    parser.add_argument(
        "--configuration-lookups",
        action="store_true",
        help="List countries, production layouts, production sorts and machines.",
    )
    parser.add_argument(
        "--resources",
        action="store_true",
        help="Summarize this center's patients, doctors, modules and intakes.",
    )
    parser.add_argument(
        "--patient-id",
        type=positive_int,
        help="Show a one-page treatment summary for this patient.",
    )
    parser.add_argument(
        "--module-id",
        type=positive_int,
        help="Summarize the submodules of this module.",
    )
    parser.add_argument(
        "--medicine-id",
        type=positive_int,
        help="Also show the field names of this medicine's center-specific view.",
    )
    parser.add_argument(
        "--include-integrations",
        action="store_true",
        help="Fetch integration rows, which may contain stored credentials.",
    )
    args = parser.parse_args()
    center_options = (
        args.resources,
        args.patient_id is not None,
        args.module_id is not None,
        args.medicine_id is not None,
        args.include_integrations,
    )
    if any(center_options) and args.center_id is None:
        parser.error("center resource options require --center-id")
    return args


def build_client() -> AmcoClient:
    """Build a client from the development credentials in `.env`."""
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


def show_collection(label: str, items: Any) -> None:
    """Print a safe collection summary without exposing full API rows."""
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{label} response is not a list of objects")
    ids = [item_id for item in items if (item_id := resource_id(item)) is not None]
    print(f"{label}: {len(items)}")
    if not ids:
        return

    preview = ", ".join(str(item_id) for item_id in ids[:ID_PREVIEW_SIZE])
    suffix = ", ..." if len(ids) > ID_PREVIEW_SIZE else ""
    print(f"  IDs: {preview}{suffix}")


def show_search_page(label: str, result: Any) -> None:
    """Print an envelope count without exposing rows from its first page."""
    if not isinstance(result, dict):
        raise TypeError(f"{label} response is not an object")
    items = result.get("items")
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        raise TypeError(f"{label} response has no object items list")
    total = result.get("maxResults", len(items))
    if not isinstance(total, int) or isinstance(total, bool):
        total = len(items)
    print(f"{label}: {total} (fetched {len(items)} rows from the first page)")


def show_fields(label: str, details: Any) -> None:
    """Print only string field names from one sensitive object."""
    if not isinstance(details, dict) or not all(
        isinstance(key, str) for key in details
    ):
        raise TypeError(f"{label} response is not an object with string keys")
    print(f"{label} fields ({len(details)}): {', '.join(sorted(details))}")


def show_centers(installation: Installation) -> list[dict[str, Any]]:
    """Example: list the bare center collection of an installation."""
    centers = installation.centers.list()
    show_collection("Centers", centers)
    return centers


def show_center_details(center: Center) -> None:
    """Example: fetch one center without printing its field values."""
    details = center.details()
    print(f"\nCenter {center.id}")
    show_fields("Detail", details)


def show_center_resources(center: Center) -> None:
    """Examples: summarize direct center resources with bounded searches."""
    active_patients = center.patients.search(
        all_items=False,
        page=1,
        is_active=True,
    )
    show_search_page("Active patients", active_patients)

    doctors = center.doctors.list()
    show_collection("Doctors", doctors)

    modules = center.modules.list()
    show_collection("Modules", modules)

    imported_medicines = center.imported_medicines.search(
        all_items=False,
        page=1,
        not_associated=True,
    )
    show_search_page("Unassociated imported medicines", imported_medicines)

    intakes = center.intakes_association.list()
    show_collection("Intakes", intakes)

    intake_groups = center.intakes_grouping.list()
    show_collection("Intake groups", intake_groups)


def show_configuration_lookups(
    client: AmcoClient,
    installation: Installation,
) -> None:
    """Examples: list the lookup collections used by the center form."""
    print("\nCenter configuration lookups")
    show_collection("Countries", client.root.countries.list())
    show_collection("Production layouts", installation.production_layouts.list())
    show_collection("Production sorts", installation.production_sorts.list())
    show_collection("Machines", installation.machines.list())


def show_patient_treatments(center: Center, patient_id: int) -> None:
    """Example: inspect a patient's treatment collection without dumping it."""
    treatments = center.patient(patient_id).treatments.search(
        all_items=False,
        page=1,
    )
    show_search_page(f"Treatments of patient {patient_id}", treatments)


def show_module_submodules(center: Center, module_id: int) -> None:
    """Example: follow a module scope to its bare submodule collection."""
    submodules = center.module(module_id).submodules.list()
    show_collection(f"Submodules of module {module_id}", submodules)


def show_customized_medicine(center: Center, medicine_id: int) -> None:
    """Example: fetch the per-center view of an installation medicine."""
    customized = center.medicine(medicine_id).customized()
    show_fields(f"Customized medicine {medicine_id}", customized)


def show_integrations(center: Center) -> None:
    """Example: fetch integrations only after the explicit CLI opt-in."""
    integrations = center.integrations.list()
    show_collection("Integrations (including inactive)", integrations)


def main() -> None:
    """Run the requested center examples."""
    args = parse_args()
    client = build_client()
    installation = client.installation(args.installation_id)

    try:
        show_centers(installation)
        if args.configuration_lookups:
            show_configuration_lookups(client, installation)
        if args.center_id is not None:
            center = installation.center(args.center_id)
            show_center_details(center)
            if args.resources:
                show_center_resources(center)
            if args.patient_id is not None:
                show_patient_treatments(center, args.patient_id)
            if args.module_id is not None:
                show_module_submodules(center, args.module_id)
            if args.medicine_id is not None:
                show_customized_medicine(center, args.medicine_id)
            if args.include_integrations:
                show_integrations(center)
    except AmcoError as exc:
        parts = [type(exc).__name__]
        if exc.error_code is not None:
            parts.append(f"error_code={exc.error_code}")
        if exc.log_correlation_id:
            parts.append(f"log_correlation_id={exc.log_correlation_id}")
        raise SystemExit(f"Amco+ request failed ({', '.join(parts)})") from None
    except ValueError:
        raise SystemExit("Invalid scoped resource selection") from None
    except (KeyError, TypeError):
        raise SystemExit("Unexpected Amco+ response shape") from None


if __name__ == "__main__":
    main()
