"""Python client for the Amco+ API (Farmadosis).

Amco+ has a conceptual hierarchy, and this library mirrors it as nested scopes:

    installation (the pharmacy)
    └── center (the care home it serves)
        └── patient
            └── treatments

Start from a client and drill down. Each level is built locally — no request is
made until you call a request method such as `details()`, `list()` or `search()`:

    from amcoplus import AmcoClient

    client = AmcoClient(login="user@example.com", password="...")

    installation_id = ...
    center_id = ...
    patient_id = ...

    installations = client.installations()
    print(f"Visible installations: {len(installations)}")

    center = client.installation(installation_id).center(center_id)
    page = center.patients.search(all_items=False, page=1, is_active=True)
    for patient in page["items"]:
        print(patient["id"])

Two naming rules hold everywhere: a **plural attribute is a collection**
(`center.patients`) and a **singular method is one item**
(`center.patient(patient_id)`).

Search-backed collections expose `list()`, `search()` and `get()` from
`Resource`. Bare-list collections expose `list()` and `get()` without adding a
`/search` suffix. See each resource class for the filters its endpoint accepts,
because Amco+ silently ignores query parameters it does not recognise.

Failures raise a subclass of `AmcoError`; catch that to catch everything.

Credentials and `base_url` are always passed in — the library never reads
environment variables or `.env` itself.
"""

from .client import DEFAULT_API_URL, AmcoClient, raise_for_error
from .exceptions import (
    AmcoError,
    APIError,
    AuthenticationError,
    NotFoundError,
    ValidationError,
)
from .resources import (
    AuthFormField,
    BareListResource,
    Center,
    DirectResource,
    Installation,
    IntegrationProvider,
    Patient,
    Resource,
    Root,
    SelectChoice,
    Treatment,
    WritableBareListResource,
)

__all__ = [
    "DEFAULT_API_URL",
    "APIError",
    "AmcoClient",
    "AmcoError",
    "AuthFormField",
    "AuthenticationError",
    "BareListResource",
    "Center",
    "DirectResource",
    "Installation",
    "IntegrationProvider",
    "NotFoundError",
    "Patient",
    "Resource",
    "Root",
    "SelectChoice",
    "Treatment",
    "ValidationError",
    "WritableBareListResource",
    "raise_for_error",
]

__version__ = "0.0.1"
