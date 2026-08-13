"""Python client for the Amco+ API (Farmadosis).

Amco+ has a strict hierarchy, and this library mirrors it as nested scopes:

    installation (the pharmacy)
    └── center (the care home it serves)
        └── patient
            └── treatments

Start from a client and drill down. Each level is built locally — no request is
made until you call something on a collection:

    from amcoplus import AmcoClient

    client = AmcoClient(login="user@example.com", password="...")

    for installation in client.installations():
        print(installation["id"], installation["name"])

    center = client.installation(65).center(417)
    for patient in center.patients.list(is_active=True):
        print(patient["id"])

Two naming rules hold everywhere: a **plural attribute is a collection**
(`center.patients`) and a **singular method is one item**
(`center.patient(3955)`).

Collections all expose `list()`, `search()` and `get()` from `Resource`. See
each resource class for the filters its endpoint accepts, because Amco+
silently ignores query parameters it does not recognise.

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
    Installation,
    IntegrationProvider,
    Patient,
    Resource,
    Root,
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
    "Installation",
    "IntegrationProvider",
    "NotFoundError",
    "Patient",
    "Resource",
    "Root",
    "ValidationError",
    "raise_for_error",
]

__version__ = "0.0.1"
