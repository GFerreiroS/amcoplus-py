"""Root scope — resources that belong to no installation at all."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

from .base import BareListResource, Resource

if TYPE_CHECKING:
    from ..client import AmcoClient

__all__ = [
    "INTEGRATION_PROVIDER_CATEGORIES",
    "AllergyCatalog",
    "AuthFormField",
    "Countries",
    "DiagnoseTypes",
    "DiagnosisCatalog",
    "DysphagiaTextures",
    "FunctionalUnits",
    "Genders",
    "IntegrationProvider",
    "IntegrationProviders",
    "InternationalClassificationDiseases",
    "LabUnits",
    "MedicineIngredients",
    "Root",
    "SelectChoice",
    "TreatmentPlans",
]


class Countries(BareListResource):
    """Countries used by center address forms — `GET /countries`.

    The endpoint returns a bare list of `{"id": int, "name": str}` rows, with
    no `/search` suffix and no pagination parameters.
    """

    path = "countries"

    def list(self, *, language: str | None = None) -> list[dict[str, Any]]:
        """Return countries, optionally localized with the `Language` header."""
        headers = {"Language": language} if language is not None else None
        return self._client.get(self.url, headers=headers)


class Genders(BareListResource):
    """Patient genders — bare `GET /genders` lookup."""

    path = "genders"


class FunctionalUnits(BareListResource):
    """Patient functional units — bare `GET /functional-units` lookup."""

    path = "functional-units"


class AllergyCatalog(BareListResource):
    """Allergy-form lookup — bare `GET /allergies`."""

    path = "allergies"


class DiagnosisCatalog(BareListResource):
    """Diagnosis-form lookup — bare `GET /diagnoses`."""

    path = "diagnoses"


class DiagnoseTypes(BareListResource):
    """Diagnosis types — bare `GET /diagnose-types`."""

    path = "diagnose-types"


class DysphagiaTextures(BareListResource):
    """Dysphagia textures — bare `GET /dysphagia-textures`."""

    path = "dysphagia-textures"


class LabUnits(BareListResource):
    """Clinical laboratory units — bare `GET /lab-units`."""

    path = "lab-units"


class TreatmentPlans(BareListResource):
    """Treatment-plan lookup — bare `GET /treatment-plans`."""

    path = "treatment-plans"


class _AutocompleteResource(Resource):
    """Search lookup whose API spells page size `items_per_page`."""

    items_per_page_param = "items_per_page"
    default_items_per_page = 100


class MedicineIngredients(_AutocompleteResource):
    """Medicine ingredients used by patient allergies.

    `GET /medicine-ingredients/search`, with `query` and `items_per_page`.
    """

    path = "medicine-ingredients"


class InternationalClassificationDiseases(_AutocompleteResource):
    """ICD diagnoses used by patient diagnosis rows.

    `GET /international-classification-diseases/search`, with `query` and
    `items_per_page`.
    """

    path = "international-classification-diseases"


class SelectChoice(TypedDict):
    """One choice of a `select` field. `key` is the value to put in
    `auth_credential`; `value` is the human label (e.g. `key="http"`,
    `value="HTTP"`). `key` is usually a string but can be an int (`schema_object`
    uses `1`/`2`).
    """

    key: Any
    value: str


class AuthFormField(TypedDict):
    """One credential field a provider asks for, from its `auth_form`.

    `name` is the key to use in the `auth_credential` you hand to
    `Center.integrations.create`; `is_required` says whether the provider will
    want it filled. `type` is the widget kind (`"text"`, `"number"`, `"password"`,
    `"select"`, `"checkbox"`, `"textarea"`, `"file"`, `"message"`).

    For a `select`, `items` holds the choices as `SelectChoice`s — pass a choice's
    `key`. A dynamic select has `items: []` and instead `options={"action": ...}`;
    fetch its choices at runtime with `Center.integrations.execute_action`.
    `options` otherwise carries per-type config: constraints like
    `{"min", "max"}` / `{"minlength", "maxlength"}`, or `{"accept": ...}` for a
    file. These are hints for building the call — the library does not enforce them.
    """

    label: str
    name: str
    type: str
    items: list[SelectChoice]
    options: Any
    is_required: bool


class IntegrationProvider(TypedDict):
    """One integration provider, as returned by `IntegrationProviders`.

    `id` is what goes in `integration_provider_id` when creating an integration;
    `auth_form` lists the credential fields it declares.
    """

    id: int
    name: str
    is_active: bool
    is_center_needed: bool
    auth_form: list[AuthFormField]


INTEGRATION_PROVIDER_CATEGORIES = (
    "productions",
    "patients-and-treatments",
    "medicines",
    "order-delivery-clients",
    "delivery-order-consumptions",
    "login-authentications",
    "control-dose-take-administrations",
    "sales",
    "counters",
    "cassettes",
)
"""The integration-provider categories Amco+ exposes.

The first nine map one-to-one to the sections of a center's INTEGRATIONS tab;
`cassettes` is an installation-side one that does not appear there. Each is a
path segment, not an id — see `Root.integration_providers`.
"""


class IntegrationProviders(Resource):
    """Available integration providers of one category (root-level).

    `/integration-providers/{category}/search`

    These are the providers a center can be wired to — the choices behind the
    "Proveedor" dropdown of each INTEGRATIONS section. Reach one through
    `Root.integration_providers(category)` rather than building it directly.

    Each item carries an `auth_form`: a list of `{label, name, type, options,
    is_required}` field descriptors telling you which credentials that provider
    needs. Those `name`s are the keys of the `auth_credential` dict you pass to
    `Center.integrations.create`. The same list is also available on its own via
    `Root.integration_provider_form`.

    Note: this endpoint's envelope counts rows in `max_results` (snake_case),
    not the `maxResults` that `/installations/search` and friends use. And it
    rejects any pagination param with a 500 — it only answers with an empty
    query string — so `default_items_per_page` is `None` here.
    """

    default_items_per_page = None

    def __init__(self, client: "AmcoClient", category: str) -> None:
        super().__init__(client, "")
        self.path = f"integration-providers/{category}"


class Root:
    """Resources that hang off no installation.

    Get it from the client rather than building it directly:

        client.root.integration_providers("productions").list()

    Patient-form dictionaries are exposed as bare lookup collections. The two
    autocomplete dictionaries (`medicine_ingredients` and
    `international_classification_diseases`) use paginated `/search` routes.
    """

    def __init__(self, client: "AmcoClient") -> None:
        self._client = client
        self.countries = Countries(client, "")
        self.genders = Genders(client, "")
        self.functional_units = FunctionalUnits(client, "")
        self.allergies = AllergyCatalog(client, "")
        self.diagnoses = DiagnosisCatalog(client, "")
        self.diagnose_types = DiagnoseTypes(client, "")
        self.dysphagia_textures = DysphagiaTextures(client, "")
        self.lab_units = LabUnits(client, "")
        self.treatment_plans = TreatmentPlans(client, "")
        self.medicine_ingredients = MedicineIngredients(client, "")
        self.international_classification_diseases = (
            InternationalClassificationDiseases(client, "")
        )

    def integration_providers(self, category: str) -> IntegrationProviders:
        """Providers of one integration `category`.

        `category` is a path segment such as `"productions"` or
        `"patients-and-treatments"` — see `INTEGRATION_PROVIDER_CATEGORIES` for
        the full set. An unknown category reaches the API and 404s.

        No request is made here; the collection is built locally.
        """
        return IntegrationProviders(self._client, category)

    def integration_provider_form(self, provider_id: int) -> list[dict[str, Any]]:
        """The dynamic credential form of a single provider.

        `GET /integration-providers/{provider_id}/integration-provider-form`

        Returns the same `auth_form` list carried by the provider's search item:
        `{label, name, type, options, is_required}` per field.
        """
        return self._client.get(
            f"/integration-providers/{provider_id}/integration-provider-form"
        )

    def unscoped_treatment(
        self,
        treatment_id: int,
        *,
        allow_unscoped: bool = False,
    ) -> dict[str, Any]:
        """Fetch `GET /treatments/{t}` without a patient ownership check.

        This global endpoint can return clinical data using only a treatment
        id. Prefer `center.patient(p).treatment(t).details()`, which verifies
        membership first. Callers that genuinely have no patient scope must
        opt in explicitly with `allow_unscoped=True`.
        """
        if not allow_unscoped:
            raise ValueError(
                "global treatment access requires allow_unscoped=True; "
                "prefer a patient-scoped treatment"
            )
        return self._client.get(f"/treatments/{treatment_id}")

    def __repr__(self) -> str:
        return "Root()"
