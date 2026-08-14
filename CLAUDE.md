# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

`amcoplus` — a private Python client library for the Amco+ API (Farmadosis), a
pharmaceutical automation platform used by pharmacies, hospitals and care homes.

The maintainer works in pharmacy IT and automation. Communicate in Spanish;
**all code, comments, docstrings and identifiers must be in English.**

## Domain model

Amco+ has a conceptual hierarchy that the library mirrors as nested scope objects:

```
installation (the pharmacy)
└── center (the care home / residence it serves)
    └── patient
        └── treatments
```

- **Installation-level resources** belong to the pharmacy: cassettes, machines,
  layouts, trays, warehouses, label designs, fill stations, users, medicines.
- **Center-level resources** belong to the residence: patients (and below them,
  treatments), doctors, modules, intakes.
- **Root-level resources** belong to no installation at all: paper rolls,
  dictionaries, licenses, translations, machine models.

A typical script targets **one installation** but iterates **several centers**
within it — e.g. updating a field on every patient of a whole installation.

## Architecture

```
src/amcoplus/
├── __init__.py           # public exports
├── client.py             # AmcoClient + raise_for_error()
├── exceptions.py         # typed exception hierarchy
└── resources/
    ├── __init__.py
    ├── base.py           # Resource: generic list()/search()/get()
    ├── root.py           # Root scope — resources with no installation
    ├── installation.py   # Installation scope + pharmacy-level resources
    ├── center.py         # Center scope + residence-level resources
    └── patient.py        # Patient/Treatment scopes + patient-tab resources
scripts/
├── test_manual.py        # integration script hitting the real API
├── centers.py            # read-only examples for center resources
├── patients_and_treatments.py  # privacy-conscious, read-only clinical examples
└── explore_api.py        # Playwright endpoint-discovery session (dev only)
```

### Layering

| Layer | Responsibility |
|---|---|
| `exceptions.py` | *What* error types exist (labels only) |
| `client.py` | *When* to raise each one; auth, token lifecycle, HTTP |
| `resources/` | Endpoint paths and domain shape |

`raise_for_error()` is the **single** place where HTTP responses are translated
into exceptions. When a new Amco+ `error_code` is discovered, add one branch
there — never spread that logic into the resource classes.

## Key design decisions

These were deliberate. Don't undo them without a reason.

**Exception subclasses are docstring-only.** `AuthenticationError`,
`NotFoundError`, `ValidationError` and `APIError` add no fields — everything
comes from `AmcoError.__init__`. They exist purely so callers can write
`except AuthenticationError` instead of checking numeric codes. A subclass only
earns an `__init__` if it carries data that is *not* in the API error envelope.

**All exception constructors are keyword-only** (`*` after `self`) to prevent
argument-order mistakes. `AmcoError.from_response(data)` builds any subclass
from the API's JSON error envelope via `cls(...)`.

**The library never reads configuration itself.** No `load_dotenv()`, no
`os.getenv()` inside `src/`. Credentials and `base_url` are passed to
`AmcoClient.__init__`. `.env` and `python-dotenv` exist only for local scripts
and are a dev dependency.

**`base_url` is a constructor parameter, not a module constant.** Amco+ is
deployed on-premise in hospitals and prisons without internet access.

**`verify_ssl: bool = True`** exists for those on-premise deployments with
self-signed certificates. Default must stay `True`; httpx's insecure-request
warnings are intentional and must not be silenced. Future improvement: accept
`bool | str` so a CA bundle path can be passed instead.

**Scope objects over hidden context.** `client.installation(5).center(8)` rather
than a mutable `set_context()`, because scripts commonly loop over centers and
shared mutable state would be a bug source. Each level receives the parent's
`base_path` and appends its own segment.

**Plural attribute = collection, singular method = one item.**
`center.patients.list()` vs `center.patient(patient_id)`. Keep this consistent when
adding resources.

**Circular imports** between `installation.py` and `center.py` are handled with
function-local imports and `TYPE_CHECKING` blocks. This is intentional.

---

# API conventions

Base URL: `https://amcoplusapi.farmadosis.com/api` (cloud default).

**Auth:** `POST /login` with `{"login", "password", "code"}` (`code` is 2FA,
usually `null`). Returns a large user payload including `access_token` and
`session_expires_at_8601` (ISO 8601, **UTC**). There is a `refresh_token` in the
response but the real flow is to log in again. Token lifetime varies per
installation, so always read `session_expires_at_8601` rather than assuming a
fixed duration. All other endpoints take `Authorization: Bearer <token>`.

Always compare expiry against `datetime.now(timezone.utc)` — never naive
`datetime.now()`, which would be local (Europe/Madrid) and silently wrong.

**List endpoints** follow `{resource}/search` and return
`{"items": [...], "maxResults": N}`. Query params: `page`, `itemsPerPage`,
plus resource-specific filters. Sorting params (`sortBy[]`, `sortDesc[]`,
`mustSort`, `multiSort`) are optional and unused.

**Single item:** `{resource}/{id}`, no `/search`.

**Not every collection paginates.** `/installations/{i}/centers` returns a bare
JSON list with no `/search` and no envelope — asking for `/centers/search`
fails with `error_code` 2014, because `search` is parsed as a center id. So
`Resource` does not fit centers, and `AmcoClient.request()` is annotated `Any`
rather than `dict`. Confirm the response shape of a new endpoint before
assuming the envelope.

**Unknown query params are ignored, not rejected.** A mistyped filter gives
unfiltered results and no error. This is why each `Resource` subclass documents
the filters its endpoint actually accepts.

**Error envelope:**
```json
{"error_code": 9001, "error_message": "Credenciales invalidas",
 "details": null, "server_number": "2", "log_correlation_id": "d176..."}
```
`error_code` is Amco+'s own numeric code and is more reliable than the HTTP
status. Known so far:

| `error_code` | HTTP | Meaning |
|---|---|---|
| 9001 | 422 | Invalid credentials |
| 1001 | 404 | The installation does not exist |
| 15003 | 404 | A real "row not found" for a single-item GET (seen on `intakes-association/{id}`) — unlike cassettes, this collection does 404 cleanly |
| 87006 | 500 | Import action found no supplier integration for the center |
| 2014 | 404 | A path segment had the wrong type, e.g. `centers/search` read as an id |
| 53001 | 422 | Field validation failed — Laravel `validation.*` rules on the request body. `details` maps each failing field path (e.g. `attributes.0.key`) to its rule |
| 11001 / 11500 / 12001 / 12004 / 15002 / 16001 | 422 | Per-resource create/update body validation (modules, doctors, submodules, intakes-grouping, intakes-association) — same idea as 53001 with resource-specific codes |
| 53002 | 422 | Request-DTO validation failed — a required query param is missing or the wrong type. Seen when a `/search` endpoint's `items_per_page` (int) is left null |
| 54002 | 404 | Route does not exist — `Not Found on GET <url>` |

Other codes are discovered as they appear — add a branch to `raise_for_error()`
and document it here.

**A missing row does not reliably give a 404.** Requesting a cassette id that
does not exist returns **HTTP 500 with an HTML body**, which comes out of
`raise_for_error()` as `APIError("Non-JSON error response (HTTP 500)")`, not
`NotFoundError`. Only bad *scope* ids (installation, center) give a real 404
with an envelope. Never promise callers a `NotFoundError` for a missing item.

## Write operations: sub-path names, mixed HTTP verbs

Writes go to a named **sub-path** (`create` / `{id}/update` / `{id}/delete`),
never a bare verb on the collection. But the HTTP method is **not** uniform —
verified across integrations, centers, doctors, modules, submodules and intakes:

| Operation | Path | HTTP method |
|---|---|---|
| create | `{resource}/create` | **POST** |
| update | `{resource}/{id}/update` | **PUT** (POST → 405) |
| delete | `{resource}/{id}/delete` | **DELETE** (POST → 405) |

So the convention is POST-create / PUT-update / DELETE-delete. (An earlier note
here claimed all three were POST and "never PUT/DELETE"; that was wrong.)
`WritableBareListResource` builds these. Caveats seen in practice:

- **Update body:** usually partial is fine (center update merges); integrations
  are the exception — their PUT wants the whole body, a partial one 500s.
- **Not every resource has all three.** Doctors, modules, intakes-association and
  intakes-grouping have create + update but **no delete** (DELETE → 404/54002).
  Only submodules (and integrations) delete.
- Still confirm a new write against the API before trusting it.

Some writes don't follow the pattern because they are actions, not CRUD:
`cassettes/{id}/medicines/add`, `cassettes/{id}/replenishes/add`,
`productions/{id}/send-to-machine`, `centers/{id}/import-patients-and-treatments`.
Those get their own named methods on the relevant scope, not `Resource` generics.

## Pagination and its traps

`itemsPerPage=-1` (everything in one response) is the default we want, and the
generous `AmcoClient` timeout exists because of it. But it is **not** universal:

**Two spellings of the same parameter.** Most endpoints use camelCase
`itemsPerPage`; a few use snake_case `items_per_page`:
`/paper-rolls/search`, `/translations/search`, `/support-access-logs`.
`/paper-roll-uploads/search` has been observed sending *both* — verify which one
it honours.

So `Resource` needs two overridable class attributes:

```python
class Resource:
    items_per_page_param: str = "itemsPerPage"
    default_items_per_page: int = -1
```

**Resources where `-1` is wrong:**

| Resource | Default | Why |
|---|---|---|
| `paper_rolls` | 10 | ~200k rows |
| `support_access_logs` | 50 (hard cap 200) | ~200k rows, **never** `-1` |
| `machine_models` | 1000 | enough to see them all |
| `medicines_families` | -1 | correct default, but very slow — warn the caller |

## Endpoints that are not JSON

`AmcoClient.request()` currently always calls `response.json()`. These endpoints
need raw bytes or `multipart` uploads, so the client needs a way to bypass that:

- **Downloads:** `machines/{id}/certificate` (a JSON *file*),
  `cassettes/export-to-atms`.
- **Uploads:** `cassettes/import-from-atms` (TXT),
  `paper-rolls/import-csv-file` (CSV),
  `all-dictionaries/{id}/medicines/import-csv-file` (CSV),
  `all-dictionaries/{id}/medicine-families/import-csv-file` (CSV).
- **Email side effect, downloads nothing:**
  `all-dictionaries/{id}/medicines/export-csv-file`,
  `all-dictionaries/{id}/medicine-families/export-csv-file`.
  Do not treat their response as the exported data.

## Intakes are NOT guarded (an earlier assumption, now disproven)

The notes used to say `centers/{c}/intakes` and `.../intake-agrupations` were
gated by center-config flags and needed a warning when off. Verified against the
API, that is wrong on two counts:

- The **real paths** are `centers/{c}/intakes-association` (the "tomas") and
  `centers/{c}/intakes-grouping`. The guessed `intakes` / `intake-agrupations`
  404 with `error_code` 54002 no matter what.
- Those real endpoints answer **200 regardless** of the config flags
  `use_intakes_association` / `use_intakes_grouping` (both on the center detail,
  booleans; `use_families_for_productions` is a related production flag). Toggling
  a flag on a beta center did not change the route, so there is **no endpoint guard
  and no warning to add** — they are plain `WritableBareListResource`s.

## Operations deliberately left out

- **`all-dictionaries/{id}/delete` is not implemented.** A dictionary must not be
  deleted casually; if someone really needs it, they do it from the web UI.
  Do not add it "for completeness".
- **Pill colours and shapes are read-only from this library.**
  `translations/search?context=medicine_pill_colors` and
  `...?context=medicine_pill_shapes` may be listed, but modifications go through
  the web UI.

## Parked center features — catalogue only

These areas are explicitly parked and non-priority. Keep the discovered routes
for reference, but do not implement resources or add script examples until the
maintainer reprioritizes them:

- **Center production plans:** `center-production-plans` (bare GET observed;
  the UI attempted POST `center-production-plans/create`, but that write was
  intercepted rather than verified against the API).
- **Center notifications:** root lookups `notification-channels` and
  `reportable-events`, plus bare `center-notification-events` under a center.
  The UI attempted a POST directly to the collection, but it was intercepted.
- **Center-scoped production operations:**
  `centers/{c}/productions/{p}/medicine-families`, `production-filters`,
  `production-filters/update` and `update`.

## API quirks — do not "fix" these

The API is inconsistent in ways that look like bugs but are real. Mirror them.

- **`medicines-families` vs `medicine-families`.** Searching and fetching a
  single medicine use `medicines-families`; creating and updating a family uses
  `medicine-families`. Both are real. Do not normalise them.
- **Nurses have no list endpoint of their own.** They are users:
  `/installations/{i}/users/search?user_type_id=3`. Creating a nurse means
  creating a user of type Nurse. And `/nurses/{id}/shifts` takes the **user id**,
  not some separate nurse id.
- **`user_role_id_to_exclude=1`** matters on `/users/search` — it hides a role
  you normally don't want listed.
- **Bare collection paths exist but are unused.** `cassettes`,
  `medication-providers`, `nurses`, `users`, `imported-medicines`,
  `medicines-families`, `machine-models` all respond without `/search`, but the
  library always goes through `/search`.
- **Productions are installation-level, but some sub-routes hang off the
  center:** `/installations/{i}/centers/{c}/productions/{p}/medicine-families`,
  `.../production-filters`, `.../production-filters/update`, `.../update`.
  Others are installation-level: `/installations/{i}/productions/{p}/fsps`.
- **Medicine customisation is per center**
  (`/installations/{i}/centers/{c}/medicines/{id}/customized` and `/customize`)
  even though the medicine itself is installation-level. There is also an
  installation-level `/installations/{i}/medicines/{id}/customize`.
- **Lookups that are not by id:** `cassettes/find-with-chip/{chip}` and
  `paper-rolls/find-by-uuid` (needs the exact uuid, otherwise 404).

---

# Scope map

```
client.installations()                     -> /installations/search
client.root                                -> resources with no installation
client.installation(i)                     -> /installations/{i}
```

```
client.root
  countries, genders, functional_units,
  allergies, diagnoses, diagnose_types,
  dysphagia_textures, lab_units,
  treatment_plans                          -> bare root lookups
  medicine_ingredients,
  international_classification_diseases    -> snake-case /search lookups
  integration_providers(category)          -> /integration-providers/{category}/search
  integration_provider_form(provider_id)
  paper_rolls, paper_roll_uploads, translations, all_dictionaries,
  licenses, machine_models
  support_access_logs                      (super-admin only)

client.installation(i)
  details()                                -> /installations/{i}
  centers, cassettes, machines, production_layouts, production_sorts, trays,
  layouts, warehouses, fill_stations, medication_providers,
  administration_routes, holiday_reasons, hospitalization_motivations,
  medicines, medicine_families, medicines_families, productions
  .cassette(x)      -> medicines.add(), replenishes.add(), history
  .machine(m)       -> configuration, certificate, bases, fsps
  .medicine(m)      -> details(), center_customization(), medicines_in_family()
  .medicine_family(f) -> details(), center_customization()
  .tray(t)
  .fill_station(f)
  .nurse(user_id)   -> shifts
  .production(p)    -> dose_takes, fsps, without_bags, save_to_machine(),
                       send_to_machine(), set_status()
  .center(c)
     patients, doctors, dose_intervals, modules, imported_medicines,
     integrations, intakes_association, intakes_grouping
     details(), update(), import_patients_and_treatments(),
     import_patient_counters(), associate_treatments()
     .module(m)     -> submodules
     .medicine(m)   -> customized(), customize()
     .patient(p)    -> treatments, allergies, diagnoses, doctors,
                       holiday_periods, hospitalization_periods, attachments,
                       sales, sale_program_codes, dose_takes
                       .treatment(t)
```

`Installation` exposes both `centers` (the bare-list collection) and `center(id)`
(the full scope), per the plural/singular rule.

---

# Endpoint catalogue

The paths below are the target surface of the library. Braced ids are
placeholders (`{i}` = installation, `{c}` = center); examples should not embed
real patient or treatment ids. Entries marked *(verify)* were transcribed from
browser traffic and have not been confirmed against the API yet.

## Root

| Path | Notes |
|---|---|
| `/countries` | **bare JSON list**, no query, `/search` or envelope. Optional `Language` header via `.list(language="en")` → `client.root.countries` |
| `/genders` | bare list → `client.root.genders` |
| `/functional-units` | bare list → `client.root.functional_units` |
| `/allergies` | bare patient-form lookup → `client.root.allergies` |
| `/diagnoses` | bare patient-form lookup → `client.root.diagnoses` |
| `/diagnose-types` | bare patient-form lookup → `client.root.diagnose_types` |
| `/dysphagia-textures` | bare patient-form lookup → `client.root.dysphagia_textures` |
| `/lab-units` | bare patient-form lookup → `client.root.lab_units` |
| `/treatment-plans` | bare treatment-form lookup → `client.root.treatment_plans` |
| `/medicine-ingredients/search` | `query`, snake-case `items_per_page`; autocomplete used by allergies → `client.root.medicine_ingredients` |
| `/international-classification-diseases/search` | `query`, snake-case `items_per_page`; autocomplete used by diagnoses → `client.root.international_classification_diseases` |
| `/treatments/{t}` | global treatment lookup used when only its id is known. It has no patient ownership context, so `client.root.unscoped_treatment(t, allow_unscoped=True)` requires an explicit unsafe opt-in |
| `/machine-models/search` | `query`, `itemsPerPage=1000`. **Not** admin-only, any user sees it |
| `/integration-providers/{category}/search` | providers a center can wire to. `category` is a path segment (see below). **Rejects any pagination param with a 500** — call it with an empty query string (`default_items_per_page=None`). Envelope counts in `max_results`, **not** `maxResults`. Each item has an `auth_form` |
| `/integration-providers/{id}/integration-provider-form` | the provider's `auth_form` on its own: `[{label,name,type,options,is_required}]` |

Integration-provider `category` values: `productions`, `patients-and-treatments`,
`medicines`, `order-delivery-clients`, `delivery-order-consumptions`,
`login-authentications`, `control-dose-take-administrations`, `sales`, `counters`,
`cassettes`. The first nine are the sections of a center's INTEGRATIONS tab.
| `/paper-rolls/search` | snake_case `items_per_page=10`, `page`. ~200k rows |
| `/paper-rolls/{id}` | single paper-roll record |
| `/paper-rolls/find-by-uuid` | exact uuid or 404 |
| `/paper-rolls/create` | |
| `/paper-rolls/import-csv-file` | CSV upload |
| `/paper-roll-uploads/search` | `page`, `itemsPerPage=-1`; sends both spellings *(verify)* |
| `/translations/search` | `items_per_page=-1`, `page`, `query`, `locale`, `context` |
| — `context=medicine_pill_colors` | medicine colours, `locale=ES`. Read-only here |
| — `context=medicine_pill_shapes` | pill shapes, `locale=EN`. Read-only here |
| `/all-dictionaries/search` | `page`, `itemsPerPage=-1`, `query` |
| `/all-dictionaries/{id}` | |
| `/all-dictionaries/create` | |
| `/all-dictionaries/{id}/update` | |
| `/all-dictionaries/{id}/delete` | **NOT IMPLEMENTED** — web UI only |
| `/all-dictionaries/{id}/medicines/export-csv-file` | sends an email, downloads nothing |
| `/all-dictionaries/{id}/medicine-families/export-csv-file` | sends an email, downloads nothing |
| `/all-dictionaries/{id}/medicines/import-csv-file` | CSV upload |
| `/all-dictionaries/{id}/medicine-families/import-csv-file` | CSV upload |
| `/support-access-logs` | **super-admin only**. `page`, `items_per_page=50` (max 200, never -1), `user_id`, `installation_id`, `center_id`, `from`, `to` |
| `/licenses/search` | `page`, `itemsPerPage=-1`, `query`, `is_active` |
| `/licenses/{id}` | |
| `/licenses/create` | |
| `/licenses/{id}/update` | |

## Installation

| Path | Notes |
|---|---|
| `/installations/search` | already implemented as `client.installations()` |
| `/installations/{i}` | installation detail → `Installation.details()` |

### Cassettes

| Path | Notes |
|---|---|
| `/installations/{i}/cassettes/search` | `is_active`, `query`, `find_deactived_cassette_medicines=0\|1`, `itemsPerPage=-1` |
| `/installations/{i}/cassettes/{id}` | |
| `/installations/{i}/cassettes/create` | |
| `/installations/{i}/cassettes/{id}/update` | |
| `/installations/{i}/cassettes/{id}/medicines/add` | action, not CRUD |
| `/installations/{i}/cassettes/{id}/replenishes/add` | action, not CRUD |
| `/installations/{i}/cassettes/{id}/history` | `itemsPerPage=-1`, `sortBy[]=created_at`, `movement_direction=recharges` |
| `/installations/{i}/cassettes/find-with-chip/{chip}` | lookup by chip, not by id |
| `/installations/{i}/cassettes/export-to-atms` | downloads a file |
| `/installations/{i}/cassettes/import-from-atms` | TXT upload |

### Machines and trays

| Path | Notes |
|---|---|
| `/installations/{i}/production-layouts` | **bare JSON list**, no query, `/search` or envelope. Confirmed → `installation.production_layouts` |
| `/installations/{i}/production-sorts` | **bare JSON list**, no query, `/search` or envelope. Confirmed → `installation.production_sorts` |
| `/installations/{i}/machines` | **bare JSON list**, no query, `/search` or envelope. Confirmed → `installation.machines` |
| `/installations/{i}/machines/{m}` | |
| `/installations/{i}/machines/{m}/configuration` | |
| `/installations/{i}/machines/{m}/certificate` | downloads a JSON file |
| `/installations/{i}/machines/{m}/bases` | |
| `/installations/{i}/machines/{m}/fsps` | |
| `/installations/{i}/machines/{m}/update` | |
| `/installations/{i}/machines/create` | |
| `/installations/{i}/trays` | |
| `/installations/{i}/trays/{t}` | |
| `/installations/{i}/trays/create` | |
| `/installations/{i}/trays/{t}/update` | |

### Fill stations

| Path | Notes |
|---|---|
| `/installations/{i}/fill-stations` | |
| `/installations/{i}/fill-stations/{f}` | |
| `/installations/{i}/fill-stations/create` | |
| `/installations/{i}/fill-stations/{f}/update` | |

### Users and nurses

| Path | Notes |
|---|---|
| `/installations/{i}/users/search` | `is_active`, `query`, `user_role_id_to_exclude=1` |
| `/installations/{i}/users/create` | |
| `/installations/{i}/users/{u}/update` | |
| `/installations/{i}/users/{u}/sessions/search` | |
| `/installations/{i}/users/{u}/user-mobile-alerts` | |
| `/installations/{i}/users/search?user_type_id=3` | this **is** the nurse list |
| `/installations/{i}/nurses/{user_id}/shifts` | id is the user id |
| `/installations/{i}/nurses/{user_id}/shifts/create` | body needs every module and submodule listed |

TODO: permissions, and assigning centers and installations to a user. Not mapped
yet — discover with `scripts/explore_api.py`.

### Medication providers

| Path | Notes |
|---|---|
| `/installations/{i}/medication-providers/` | bare list used by patient sales → `installation.medication_providers` |
| `/installations/{i}/medication-providers/create` | |
| `/installations/{i}/medication-providers/update` | observed **without an id** in the path — *(verify)*, it should be `/{id}/update` |

### Patient and treatment form lookups / sales actions

| Path | Method | Notes |
|---|---|---|
| `/installations/{i}/administration-routes` | GET | bare treatment-form lookup → `installation.administration_routes` |
| `/installations/{i}/holiday-reasons` | GET | direct `{"items", "maxResults"}` envelope → `installation.holiday_reasons` |
| `/installations/{i}/holiday-reasons/create` | POST | `{description, installation_id}` |
| `/installations/{i}/holiday-reasons/{id}/delete` | DELETE | |
| `/installations/{i}/hospitalization-motivations/search` | GET | standard envelope → `installation.hospitalization_motivations` |
| `/installations/{i}/hospitalization-motivations/create` | POST | `{description}` |
| `/installations/{i}/hospitalization-motivations/{id}/delete` | DELETE | |
| `/installations/{i}/import-sales` | POST | opaque installation-wide JSON document; high impact → `installation.import_sales()` |
| `/installations/{i}/sales/{sale}/sale-lines/{line}/update` | PUT | `{should_sum_to_counters}`; no independently verified item lookup, so `installation.update_sale_line_counter(..., allow_unverified_scope=True)` requires ids derived from a trusted sales row |
| `/installations/{i}/medicines/{m}/medicines-in-family` | GET | treatment-editor lookup → `installation.medicines_in_family(m)` |
| `/installations/{i}/ws-treatment` | GET | repeated `cic_ids[]`; synchronization button. Possible server-side effects are unverified → `installation.ws_treatments(..., allow_possible_side_effect=True)` |

### Medicines and families

| Path | Notes |
|---|---|
| `/installations/{i}/medicines/search` | treatment medicine autocomplete; `query`, `with_count=false` → `installation.medicines` |
| `/installations/{i}/medicines/{id}` | selected medicine → `installation.medicine(id).details()` |
| `/installations/{i}/medicines/{id}/centers/{c}/customize` | **GET** center projection used by treatment editor → `.center_customization(c)`; distinct from the inverse-path center resource below |
| `/installations/{i}/medicine-family-levels/search` | `page`, `itemsPerPage`; treatment family filter → `installation.medicine_family_levels` |
| `/installations/{i}/medicine-families/search` | `query`, `medicine_family_level_id` → `installation.medicine_families` |
| `/installations/{i}/medicine-families/{id}` | selected family → `installation.medicine_family(id).details()` |
| `/installations/{i}/medicine-families/{id}/centers/{c}/customize` | **GET** customized family projection → `.center_customization(c)` |
| `/installations/{i}/medicines-families/search` | older combined collection (plural `medicines-`); `is_active`, `is_family`, `is_medicine`, `with_count` → `installation.medicines_families` |
| `/installations/{i}/medicines-families/medicines/{id}` | single medicine |
| `/installations/{i}/medicines/create` | |
| `/installations/{i}/medicines/{id}/update` | |
| `/installations/{i}/medicines/{id}/customize` | installation-level customisation |
| `/installations/{i}/medicines/{id}/community-characteristics` | |
| `/installations/{i}/centers/{c}/medicines/{id}/customized` | GET, per-center view → `center.medicine(id).customized()` |
| `/installations/{i}/centers/{c}/medicines/{id}/customize` | **PUT** (POST → 405), → 202, per-center overrides → `center.medicine(id).customize(**fields)` |
| `/installations/{i}/medicine-families/create` | note the singular `medicine-` |
| `/installations/{i}/medicine-families/{id}/update` | |

### Productions

Low priority — the production module is huge and will barely be used. The four
center-scoped routes at the end of this table are explicitly parked and should
not be implemented until the maintainer reprioritizes them.

| Path | Notes |
|---|---|
| `/installations/{i}/productions/search` | `production_status_ids[]` (repeatable), `created_at=YYYY-MM-DD`, `sortBy[]=id` |
| `/installations/{i}/productions/{p}/without-bags` | |
| `/installations/{i}/productions/{p}/dose-takes/search` | |
| `/installations/{i}/productions/{p}/save-to-machine` | |
| `/installations/{i}/productions/{p}/send-to-machine` | |
| `/installations/{i}/productions/{p}/set-status` | |
| `/installations/{i}/productions/{p}/fsps` | |
| `/installations/{i}/productions/{p}/fsps/{id}` | |
| `/installations/{i}/centers/{c}/productions/{p}/medicine-families` | center-scoped — **PARKED** |
| `/installations/{i}/centers/{c}/productions/{p}/production-filters` | center-scoped — **PARKED** |
| `/installations/{i}/centers/{c}/productions/{p}/production-filters/update` | center-scoped — **PARKED** |
| `/installations/{i}/centers/{c}/productions/{p}/update` | center-scoped — **PARKED** |

### Already implemented, endpoint names unverified

`layouts` (separate from the verified `production_layouts`) and `warehouses` —
first-pass guesses. Confirm against the API.

## Center

| Path | Notes |
|---|---|
| `/installations/{i}/centers` | **bare JSON list**, no `/search`, no envelope. Confirmed |
| `/installations/{i}/centers/create` | POST center creation → `installation.centers.create(**fields)` |
| `/installations/{i}/centers/{c}` | center detail (object). Confirmed → `Center.details()` |
| `/installations/{i}/centers/{c}/update` | **PUT** (POST → 405), **partial body** accepted (merges) → `Center.update(**fields)` |
| `/installations/{i}/centers/{c}/import-patients-and-treatments` | action, **POST** (PUT → 405). Pulls from the center's supplier integration; none → 500 / `error_code` 87006 |
| `/installations/{i}/centers/{c}/import-patients-counters` | mutating POST integration action → `Center.import_patient_counters()` |
| `/installations/{i}/centers/{c}/associate-treatments` | mutating center-wide POST, no preview → `Center.associate_treatments()` |
| `/installations/{i}/centers/{c}/patients/search` | GET, `itemsPerPage` pagination, `{"items", "maxResults"}` envelope. `is_active` and `query` filters → `center.patients.search()` / `.list()` |
| `/installations/{i}/centers/{c}/patients/{p}` | GET patient detail object → `center.patient(p).details()` or `center.patients.get(p)` |
| `/installations/{i}/centers/{c}/patients` | bare GET used by the treatment-review screen; filters include `is_active`, `are_all_treatments_reviewed` → `center.patients.direct_list()` |
| `/installations/{i}/centers/{c}/dose-intervals` | bare GET, `medicine_id` or `medicine_family_id`; treatment editor → `center.dose_intervals` |
| `/installations/{i}/centers/{c}/intakes-association` (+ `/{id}`) | the intakes ("tomas"): bare list, create/update, no delete → `center.intakes_association`. **Real path** — not the `intakes` guessed earlier |
| `/installations/{i}/centers/{c}/intakes-grouping` | intake groupings: bare list, create/update, no delete → `center.intakes_grouping`. **Real path** — not `intake-agrupations` |
| `/installations/{i}/centers/{c}/imported-medicines/search` | `itemsPerPage=-1`, `not_associated=true\|false` → `center.imported_medicines` |
| `/installations/{i}/centers/{c}/doctors` (+ `/{d}`, `/create`, `/{d}/update`) | bare list; create (POST), update (PUT), no delete → `center.doctors` |
| `/installations/{i}/centers/{c}/doctors/specializations` | bare lookup → `center.doctors.specializations()` |

### Integrations (the INTEGRATIONS tab)

A center's configured integrations are the resource
`integration-provider-customizations`. **Bare JSON list** (no `/search`, no
envelope), like centers. The providers themselves are root-level (above).

| Path | Method | Notes |
|---|---|---|
| `.../integration-provider-customizations` | GET | bare list, **includes soft-deleted (`is_active=false`) rows** |
| `.../integration-provider-customizations/{id}` | GET | single |
| `.../integration-provider-customizations/create` | POST | → 201. body: `{integration_provider_id, auth_credential:{...}, type_frequency:"manual", frequency:"weekly", at_day, at_hour, at_minute}` |
| `.../integration-provider-customizations/{id}/update` | **PUT** | → 202, **whole body** (same fields as create; a partial one 500s) |
| `.../integration-provider-customizations/{id}/delete` | **DELETE** | → 204, **soft delete** (sets `is_active=false`; row stays in the list) |
| `.../integration-provider-customizations/{id}/check` | POST | test the connection ("Comprobar conexión"). → 200 `{accepted, reason}`; a provider that can't connect answers 500. GET → 405 |
| `.../integration-provider-customizations/{id}/execute-action` | POST | dynamic-option lookups (see below) |

The **create response wraps the row in `{"data": ...}`** (unlike the GET, which
is bare) — `create` unwraps it and returns the record with its new `id`. For a
file/webhook provider that record carries the ingest URLs `public_url_absolute`
(the webhook to POST data to), `private_url_absolute`, `public_soap_url_absolute`
and `url_signature`; a plain GET of the row does not include them. A new
integration only takes effect once `check` passes.

**Select field choices live in `items`, not `options`.** A `select` field in the
`auth_form` carries its choices under an **`items`** key: `[{key, value}]`, where
**`key` is the value to put in `auth_credential`** and `value` is the display label
(`protocol` → `[{key:"http", value:"HTTP"}, ...]`, so send `"http"`). `key` is
usually a string but can be an int (`schema_object`: `1`/`2`).
`Integrations.select_choices(field)` returns `{key: label}`. Known static selects:

| field | keys |
|---|---|
| `protocol`, `aegerus_protocol` | http, https, ftp, ssh, smb |
| `text_encode_type` | UTF-8, UTF-16, ISO-8859-1, ISO-8859-6, ISO-8859-15, Windows-1252 |
| `date_format_type` | Ymd, YmdHis, Y-m-d, `Y-m-d H:i:s`, dmY, dmYHis, d-m-Y, `d-m-Y H:i:s` |
| `schema_object` | 1 (Stored Procedure), 2 (View) |
| `environment` | P, T |
| `nexa_api_environment` | pre, pro |
| `delivery_production_dose_take_consumption_type` | DISPENSED, NOT_PACKABLE, DISPENSED_AND_NOT_PACKABLE |

**Dynamic option fields.** A dependent dropdown has `items: []` and instead an
`options` of `{"action": "<name>"}` — its choices are fetched live via
`execute-action`, body `{"action": <name>, "attributes": [{"key","value"}, ...]}`
where attributes are the credential values the action needs (`Integrations.execute_action`
takes a plain mapping and shapes it; needs a real integration `{id}`). Known
actions: `request_centers` (`resiplus_center`),
`request_farmadosis_installations` (`installation_id`),
`request_farmadosis_centers` (`center_id`).

**Writes follow the general POST-create / PUT-update / DELETE-delete convention**,
with two quirks specific to this resource: the PUT update wants the **whole** body
(a partial one 500s), and DELETE is a **soft** delete (`is_active=false`, row
stays in the list — there is no hard delete). Both return no body (202/204), which
is why `request()` returns `None` on empty content.

`auth_credential` keys are the chosen provider's `auth_form` field `name`s, and it
holds **every** field's value (the web form dumps them all in): `text`/`textarea`/
`password` as strings, `number` as a string/number, `checkbox` as a bool, `select`
as the chosen `key`. `file` fields are not included (they are the data channel).
Nothing else moves to the top level — the create body envelope
(`integration_provider_id`, `auth_credential`, `type_frequency`, `frequency`,
`at_day`, `at_hour`, `at_minute`) is the same for every provider and category.
The library never validates it: `create`/`update` send whatever they are given.

**One endpoint serves all nine categories** — the category and provider are not
in the path, only `integration_provider_id` in the body — so `center.integrations`
creates any provider of any section. The category only decides which provider
list you pull from (`client.root.integration_providers(category)`).

**`auth_form` field types**, across all categories: `text`, `textarea`, `number`,
`password`, `select` (choices in `items`, see below), `checkbox` are real credential
inputs and go in `auth_credential`; `file` is the data channel (the integration
exposes an upload URL — not sent at create); `message` is help text; a `"undefined"`
name is UI noise. `Integrations.credential_template` /
`missing_credential_fields` count only the real inputs, so a file-only provider
(e.g. AMCO+ JSON) is creatable with `auth_credential={}` and a DB provider
(e.g. Ekon Mutuam) yields its host/user/password/... to fill.

**Dead routes — the SPA calls these but they 404 (54002). Do not implement:**
`.../center-integrations`, `.../production-integrations`, `.../integrations`.

### Modules and submodules

Implemented: `center.modules` (bare list, create/update, **no delete**) and
`center.module(m).submodules` (bare list, create/update/**delete**).

| Path | Method | Notes |
|---|---|---|
| `/installations/{i}/centers/{c}/modules` (+ `/{m}`) | GET | bare list / single |
| `/installations/{i}/centers/{c}/modules/create` | POST | |
| `/installations/{i}/centers/{c}/modules/{m}/update` | PUT | no module delete (DELETE → 404/54002) |
| `/installations/{i}/centers/{c}/modules/{m}/submodules` (+ `/{s}`) | GET | bare list / single |
| `/installations/{i}/centers/{c}/modules/{m}/submodules/create` | POST | |
| `/installations/{i}/centers/{c}/modules/{m}/submodules/{s}/update` | PUT | |
| `/installations/{i}/centers/{c}/modules/{m}/submodules/{s}/delete` | DELETE | |

## Patient

`center.patient(p)` builds a local scope and makes no request. The beta patient
record has five tabs: Information, Clinical data, Sales, Takes and Mobile
alerts. The first four are mapped below. Core list/detail GETs and the documented
response envelopes were checked on beta using schema-only output; bag and
production helpers without a derivable row remain SPA-observed. Treatment
detail and the backend's cross-patient mismatch behaviour were checked without
retaining or printing field values.

Mutation routes and bodies are taken from the current SPA. Beta accepted an
unchanged full-object patient PUT with no observed field differences, and a
temporary attachment completed create/update/download/delete with cleanup.
Those requests may still leave audit records. Most other write response shapes
remain intentionally typed as `Any` until a real workflow exercises them.

### Information

| Path | Method | Public API / notes |
|---|---|---|
| `.../centers/{c}/patients` | GET | bare list in addition to `/search` → `center.patients.direct_list()` |
| `.../centers/{c}/patients/search` | GET | `itemsPerPage`, `page`, `is_active`, `query`; `{"items", "maxResults"}` → `center.patients.search()` |
| `.../centers/{c}/patients/create` | POST | patient-form fields → `center.patients.create(**fields)` |
| `.../patients/{p}` | GET | complete identity, contact, location and clinical record → `patient.details()` |
| `.../patients/{p}/update` | PUT | the SPA sends the **complete** edited patient object → `patient.update(record)`; partial semantics are not assumed |
| `.../patients/{p}/activate` / `deactivate` | PUT | no body → `patient.activate()` / `.deactivate()` |
| `.../patients/{p}/set-image-patient` | POST | multipart `image` → `patient.set_image()` |
| `.../patients/{p}/doctors` | GET | bare list → `patient.doctors.list()` |
| `.../patients/{p}/assign-doctor` | POST | `{doctor_id, doctor_specialization_id}` → `patient.doctors.assign()` |
| `.../patients/{p}/update-doctor/{association_id}` | POST | same body → `patient.doctors.update_assignment()` |
| `.../patients/{p}/unassign-doctor/{association_id}` | POST | no body → `patient.doctors.unassign()` |
| `.../patients/{p}/holiday-periods` | GET | direct `{"items", "maxResults"}` envelope → `patient.holiday_periods.search()` / `.list()` |
| `.../holiday-periods/create` | POST | full period form object → `patient.holiday_periods.create()` |
| `.../holiday-periods/{id}/update` | PUT | full edited period → `.update()` |
| `.../holiday-periods/{id}/delete` | DELETE | → `.delete()` |
| `.../patients/{p}/hospitalization-periods/search` | GET | standard envelope → `patient.hospitalization_periods.search()` |
| `.../hospitalization-periods/create` | POST | form object → `.create()` |
| `.../hospitalization-periods/{id}/update` | PUT | full edited period → `.update()` |
| `.../hospitalization-periods/{id}/deactivate` | PUT | no body → `.deactivate()` |
| `.../patients/{p}/attachments/search` | GET | nonstandard `{"data": [...]}` → `patient.attachments.search()` / `.list()` |
| `.../attachments/create` | POST | multipart `file` + `title` → `.create()` |
| `.../attachments/{a}/download` | GET | raw bytes → `.download()`; never auto-writes a local file |
| `.../attachments/{a}/update` | PUT | `{title}` → `.update()` |
| `.../attachments/{a}/delete` | DELETE | → `.delete()` |
| `.../patients/{p}/electronic-prescription` | GET | returns handoff fields including `post_url` → `patient.electronic_prescription()` |

The API does not consistently enforce nested ownership. `_PatientScopeGuard`
validates the returned patient `id` and `center_id`; patient writes repeat that
preflight and force scoped ids into their bodies. Item writes first require an
exact id in the patient-scoped doctors/periods/attachments/clinical/code
collection. Unobserved inherited item GETs are replaced by safe collection
lookups (or disabled for sales).

The electronic-prescription UI subsequently POSTs to the returned external
URL. The library deliberately does **not** perform or model that external POST.

### Clinical data

Scalar clinical fields (weight, height, creatinine, autonomy and dysphagia)
live on the main patient object and use the same full-object `patient.update()`.

| Path | Method | Public API / notes |
|---|---|---|
| `.../patients/{p}/diagnoses/search` | GET | `itemsPerPage`, `page`, `is_active`; standard envelope → `patient.diagnoses.search()` |
| `.../patients/{p}/diagnoses/create` | POST | diagnosis form object → `.create()` |
| `.../patients/{p}/diagnoses/{id}/deactive` | POST | API spelling is `deactive` → `.deactivate(id, payload)` |
| `.../patients/{p}/allergies/search` | GET | same pagination → `patient.allergies.search()` |
| `.../patients/{p}/allergies/create` | POST | allergy form object → `.create()` |
| `.../patients/{p}/allergies/{id}/deactive` | POST | → `.deactivate(id, payload)` |

These two search endpoints reject the textual `true`/`false` produced by httpx
for a Python boolean and require `1`/`0`. `_ClinicalRows.search()` normalizes
`is_active=True/False` automatically.

The SPA's deactivation payload has keys `deactivate_reason` and `is_active`, but
the current build appears to pass an object in `is_active` in one path. The SDK
therefore accepts an explicit mapping and does not falsely type it as `bool`.
Clinical lookups are `client.root.allergies`, `.diagnoses`, `.diagnose_types`,
`.lab_units`, `.dysphagia_textures`, `.medicine_ingredients` and
`.international_classification_diseases`.

### Treatments

Patients and treatments both support a direct bare list **and** a paginated
`/search`; beta returned 200 for both variants. The SDK keeps `/search` as the
normal bounded interface and names the envelope-less variant `direct_list()`.

| Path | Method | Public API / notes |
|---|---|---|
| `.../patients/{p}/treatments` | GET | bare list → `patient.treatments.direct_list()` |
| `.../patients/{p}/treatments/search` | GET | `itemsPerPage`, `page`, standard envelope → `.search()` / `.list()` |
| `.../patients/{p}/treatments/{t}` | GET | direct object → `.get(t)` or `patient.treatment(t).details()` |
| `.../patients/{p}/treatments/create` | POST | complete treatment including `configs` → `.create(record)` |
| `.../treatments/{t}/update` | PUT | complete treatment + configs → `patient.treatment(t).update(record)` |
| `.../treatments/{t}/activate` / `deactivate` | PUT | → `patient.treatment(t).activate()` / `.deactivate()` |
| `.../treatments/{t}/with-configs` | GET | editable treatment + configs → `.with_configs()` |
| `.../treatments/{t}/treatment-config` | GET | configuration list → `.treatment_config()` |
| `.../treatments/{t}/search-historical` | GET | historical-version envelope → `.search_historical()` |
| `.../treatments/{t}/review-approve` | POST | pre-production approval → `.review_approve()` |
| `.../treatments/{t}/review-reject` | POST | `{pre_production_review_rejected_reason}` → `.review_reject(reason=...)` |
| `.../patients/{p}/treatments/medical-order` | GET | patient projection with `medical_order_lines` → `patient.treatments.medical_order()` |
| `.../treatments/check-medicine-ingredient-interactions` | GET | optional `medicine_id` or `medicine_family_id` → `.check_medicine_ingredient_interactions()` |
| `.../treatments/check-diagnoses-and-allergies` | GET | clinical conflict list → `.check_diagnoses_and_allergies()` |
| `.../treatments/check-medicine-ingredient-overdose` | GET | optional medicine/family filter → `.check_medicine_ingredient_overdose()` |

**Backend ownership caveat:** beta accepts a treatment id from another patient
on the nested `.../patients/{p}/treatments/{t}` route. Searches cannot reliably
prove membership because inactive rows are omitted by default and `query` does
not match ids. The SDK therefore preflights the item, validates the response's
own `patient_id`, discards a mismatch, and repeats that check before every
subsequent item read or mutation. Never combine patient and treatment ids from
different sources. The global `/treatments/{t}` lookup cannot perform this
check and is deliberately exposed only as the explicit opt-in
`client.root.unscoped_treatment(t, allow_unscoped=True)`.
This client-side preflight is a misuse guard with an unavoidable TOCTOU window;
the backend must enforce ownership atomically for a security boundary.

Treatment writes require the SPA's explicit `configs` list, including an empty
list when appropriate. A `with-configs` response is not itself a write body:
the SPA submits those rows under `configs`. Create rejects reusable treatment
or config ids; update accepts only config ids already returned for that
treatment and pins every parent id to the scoped patient/treatment.

Treatment create/update/status calls accept optional `authenticate_code` and
`step_up_grant`; these become the SPA's `authenticateCode` and
`X-Step-Up-Grant` headers. The authenticated client always writes its own
`Authorization` last, so custom headers cannot replace the Bearer token.
The supporting authentication flow is `client.send_two_factor_code()`
(`GET /two-factor/send`, which sends a real code),
`client.create_step_up_challenge(purpose="treatment-edit")` and
`client.verify_step_up(challenge_id, code)`. Never log the returned grant.

| Supporting path | Method | Body / effect |
|---|---|---|
| `/two-factor/send` | GET | sends a real code to the authenticated user |
| `/auth/step-up/challenge` | POST | `{purpose: "treatment-edit"}` → challenge id and expiry |
| `/auth/step-up/verify` | POST | `{challengeId, code}` → short-lived secret grant and expiry |

Supporting lookups/actions are `client.root.treatment_plans`,
`installation.administration_routes`, `center.dose_intervals`,
`installation.medicines`, `.medicine_family_levels`, `.medicine_families`,
`.medicine(id)`, `.medicine_family(id)`, `installation.medicines_in_family()`,
`installation.ws_treatments(..., allow_possible_side_effect=True)` and
`center.associate_treatments()`.

### Sales

| Path | Method | Public API / notes |
|---|---|---|
| `.../patients/{p}/sales` | GET | direct paginated envelope; `itemsPerPage`, `page`, `query` → `patient.sales.search()` / `.list()` |
| `.../patients/{p}/sale-program-codes/list` | GET | bare list → `patient.sale_program_codes.list()` |
| `.../sale-program-codes/create` | POST | `{patient_id, medication_provider_id, code, id:null}` → `.create()` |
| `.../sale-program-codes/{id}/update` | PUT | full edited row → `.update()` |
| `.../sale-program-codes/{id}/delete` | DELETE | → `.delete()` |

The installation-wide sales import and sale-line counter update are mapped on
`Installation` above. They can affect data beyond one patient and have no
read-only example.

### Takes (dose administration)

Do not call these resources `intakes`: `center.intakes_association` and
`.intakes_grouping` configure time slots, whereas patient `dose_takes` are real
administration events.

| Path | Method | Public API / notes |
|---|---|---|
| `.../patients/{p}/dose-takes-control` | GET | `itemsPerPage`, `page`, `is_active`, `query`, `date_at`; object of three arrays → `patient.dose_takes.search(date_at=...)` |
| `.../patients/{p}/bags/{bag}/dose-takes-control` | GET | same three-array shape; no ownership lookup exists, so `.for_bag(..., allow_unverified_scope=True)` requires a trusted scanner id and explicit opt-in |
| `.../patients/{p}/takes-simulate` | POST | mutating simulation → `.simulate()` |
| `.../patients/{p}/patient-dose-takes/{id}/mark-taken` | POST | auditable action → `.mark_taken(id, control=control)`; requires a positive match in a patient array of a control response loaded for this scope |
| `.../patient-dose-takes/{id}/mark-rejected` | POST | `{reason}` → `.mark_rejected(id, control=control, reason=...)`; same preflight |
| `/installations/{i}/productions/{prod}/patients/{p}/dose-takes` | GET | no independent ownership lookup; `.production_patient(..., allow_unverified_scope=True)` requires a trusted production id |
| `/installations/{i}/productions/{prod}/dose-takes/{id}/mark-taken` | POST | `.mark_production_taken(prod, id, control=control, allow_unverified_scope=True)`; requires `(production_id, id)` in the production-only control array plus explicit risk opt-in |
| `.../dose-takes/{id}/mark-rejected` | POST | `{reason}` → `.mark_production_rejected(..., control=control, reason=..., allow_unverified_scope=True)`; same preflight |

Mark/reject/simulate alter medication-administration state and may record the
acting user and timestamp. They are exposed explicitly but never run by example
scripts.

### Mobile alerts — documentation only

This tab depends on `patient.user.id` and `patient.user.mobile_device_id`. It
exists, but is deliberately not implemented in the Python API:

| Path | Method | Notes |
|---|---|---|
| `/installations/{i}/users/{u}/user-mobile-alerts` | GET | `itemsPerPage`, `page`; `{"items", "max_results"}` |
| `/installations/{i}/users/{u}/mobile-device/{device}` | GET | device eligibility lookup |
| `/installations/{i}/centers/{c}/patients/{p}/send-mobile-notification` | POST | `{title, body}`; external user-visible effect |

### Explicitly excluded

By maintainer decision, do not add public methods for these routes:

- `GET /installations/{i}/centers/{c}/treatments-bulk`
- `PUT /installations/{i}/centers/{c}/treatments-bulk/update`
- `GET /languages/search`
- `GET /after-login?installation_id={i}&center_id={c}`

### Safe examples

Patient-tab examples must use bounded pages where the endpoint supports them
and explicit section flags. Bare/direct endpoints may still fetch every row,
so limit their output to counts and a small preview of internal IDs. For detail
objects, print only sorted field names. Never print names, contact details,
external identifiers,
medicines, doses, diagnoses, notes, sales, rejection reasons or complete rows.
Even internal ids and dates are linkable metadata. Mutating imports, review,
clinical deactivation and dose-take actions do not belong in read-only scripts.
Any future mutation script must fail closed: target only an explicitly
allowlisted test installation/center/patient, require a separate execute flag,
confirm the scoped id, and restore reversible changes in `finally`. Do not add
executable examples for dose takes, mobile notifications, treatment review or
installation-wide sales imports.

## Not catalogued yet

Many more endpoints exist and will be added over time. Use
`scripts/explore_api.py` to discover them rather than guessing.

---

# Adding a resource

Two steps:

```python
# 1. in resources/root.py, resources/installation.py or resources/center.py
class Layouts(Resource):
    path = "layouts"

# 2. register it in the owning scope's __init__
self.layouts = Layouts(client, self._base_path)
```

`list()`, `search()` and `get()` come from `Resource` for free. Override
`items_per_page_param` or `default_items_per_page` when the catalogue above says
the resource needs it. Put it under `Root` if it has no installation in its path,
under `Installation` if it belongs to the pharmacy, under `Center` if it belongs
to the residence.

# Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/test_manual.py
```

Runtime dependency: `httpx` only. Dev: `python-dotenv`, `playwright`.

`scripts/test_manual.py` reads credentials from `.env` at the repo root and hits
the real API. `.env` is gitignored; `.env.example` documents the variables.

## Endpoint discovery (`scripts/explore_api.py`)

Drives Chrome through Playwright against the **test environment** to find
endpoints, query params and request bodies. It blocks service workers and
routes the whole browser context so non-API mutations cannot bypass the API
handler. API-looking requests from an origin outside the web/API allowlist are
blocked entirely; set `AMCO_BASE_URL` when beta uses a separate API origin:

- **Mode A** — aborts mutating HTTP methods (except login/refresh) and the known
  side-effecting GETs (`two-factor/send`, treatment synchronization and both
  email-sending dictionary exports). Non-API POST/PUT/PATCH/DELETE requests are
  also aborted. Unknown GETs still require judgment: the HTTP verb is not a
  no-side-effect guarantee.
- **Mode B** — fills a create/update form, derives only the JSON schema and
  top-level body keys from `request.post_data()`, and aborts the request anyway.
  The web UI will show a network error; that is expected. Consult the SPA source
  in a controlled environment when exact field semantics are required.

Traffic goes to `artifacts/` (gitignored). New captures record **schema only**:
known identifier segments are normalized, query values are reduced to parameter
names, and bodies/responses to keys and types. An unknown route may still carry
an unrecognized identifier in its path. Older traffic files may contain raw
paths, query values or write bodies, and `browser-state.json` contains a reusable
authenticated session.
Screenshots under `artifacts/shots/` can show
unredacted identity or clinical data. Treat the entire directory as secret
material, keep the directory at mode `0700` and files at `0600`, never commit,
share or attach it, and purge it when the discovery session is no longer
needed. The interception guard is defense in depth, not a browser sandbox.

# Rules

- **Never commit credentials.** No passwords, tokens or `.env` contents in
  source, tests, comments or commit messages.
- **Never print full API payloads** in examples or debug output — they contain
  real patient data, pharmacy names and tax IDs. Print field names, counts or
  non-secret internal IDs only. Never print even fragments of tokens,
  passwords, authentication codes or grants.
- Keep `raise_for_error()` as the only place that maps responses to exceptions.
- Prefer adding a `Resource` subclass over writing raw `client.get()` calls.
- No code at module scope in `src/` that performs I/O. Importing `amcoplus` must
  never hit the network.

## Commits

**Small, self-contained commits.** One reason to change per commit, with a
subject line that says what it does. Never bundle unrelated work — a resource
class, a tooling change and a doc update are three commits, not one.

If a change grew large while working, split it before committing rather than
writing a commit message with "and" in it.

# Status

Working: exception hierarchy, `raise_for_error()`, `AmcoClient` (login, token
storage, expiry check, authenticated JSON and raw-byte requests), resource
scopes for installation / center / patient / treatment, installable package.
`BareListResource` for envelope-less collections and `DirectResource` for a
pagination envelope returned directly from the collection path.
Center integrations (`center.integrations`, with `create`/`update`/`delete`).
`Center.details()` / `update()` / the import and association actions, plus
`center.doctors`, `.modules` + `.module(m).submodules`, `.imported_medicines`,
`.dose_intervals`, `.intakes_association`, `.intakes_grouping`, and
`Installation.centers` — bare-list writes come from
`WritableBareListResource`. Center-form lookups:
`client.root.countries`, `installation.production_layouts`,
`.production_sorts`, and the corrected bare-list `installation.machines`.
Patient Information, Clinical, Sales and Takes resources are mapped in
`resources/patient.py`, including full patient/treatment writes, attachments,
doctor assignments, periods, clinical rows, treatment configuration/history
and review, program codes and dose-take actions. Root/installation patient-form
lookups are registered. Mobile alerts are catalogue-only by explicit decision.

Not done yet:
- **Generic writes on every `Resource`** and unrelated named actions such as
  cassette `add` or production `send-to-machine`. Verified resources expose
  their own explicit write methods; do not assume every collection supports the
  same verbs.
- **Other non-JSON uploads/downloads.** The client now supports raw bytes and
  patient multipart uploads, but CSV/TXT import/export resources still need
  their own endpoint methods.
- **Remaining `Root` resources:** paper rolls, dictionaries, licenses,
  translations, machine models and support access logs. Languages are an
  explicit non-goal for the current patient work.
- **Unit tests.** Deliberately deferred. When added, use `respx` to mock httpx
  and cover `raise_for_error()` branches, `is_token_valid()` edge cases (no
  token, just-expired, timezone handling) and re-login behaviour. Do not add
  tests that merely assert constructor assignments.
- **Automatic re-login on 401.** Retry exactly once, then fail — never loop.
- **Reusable `httpx.Client`** plus `close()` and context-manager support;
  currently each request opens a new connection.
- **Logging** via a `logging.getLogger("amcoplus")` logger. Never log tokens or
  credentials.
- Most resource classes — only a first pass exists; verify actual endpoint names
  against the API before trusting them.
