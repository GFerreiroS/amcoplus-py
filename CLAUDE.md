# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

`amcoplus` — a private Python client library for the Amco+ API (Farmadosis), a
pharmaceutical automation platform used by pharmacies, hospitals and care homes.

The maintainer works in pharmacy IT and automation. Communicate in Spanish;
**all code, comments, docstrings and identifiers must be in English.**

## Domain model

Amco+ has a strict hierarchy that the library mirrors as nested scope objects:

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
    └── center.py         # Center and Patient scopes + their resources
scripts/
├── test_manual.py        # integration script hitting the real API
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
`center.patients.list()` vs `center.patient(3955)`. Keep this consistent when
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
| 53002 | 422 | Request-DTO validation failed — a required query param is missing or the wrong type. Seen when a `/search` endpoint's `items_per_page` (int) is left null |
| 54002 | 404 | Route does not exist — `Not Found on GET <url>` |

Other codes are discovered as they appear — add a branch to `raise_for_error()`
and document it here.

**A missing row does not reliably give a 404.** Requesting a cassette id that
does not exist returns **HTTP 500 with an HTML body**, which comes out of
`raise_for_error()` as `APIError("Non-JSON error response (HTTP 500)")`, not
`NotFoundError`. Only bad *scope* ids (installation, center) give a real 404
with an envelope. Never promise callers a `NotFoundError` for a missing item.

## Write operations: Amco+ is not verb-REST

Writes are `POST` requests to a **sub-path**, not HTTP verbs on the collection:

| Operation | Path | HTTP method |
|---|---|---|
| create | `{resource}/create` | POST |
| update | `{resource}/{id}/update` | POST |
| delete | `{resource}/{id}/delete` | POST |

**Never** map these to `PUT`, `PATCH` or HTTP `DELETE`. When `Resource` grows
`create()` / `update()` / `delete()`, they must build these paths.

The rule holds almost everywhere, but it is not absolute — confirm a new write
against the API before trusting it. `integration-provider-customizations` is the
known exception: its update is a **PUT** and its delete an HTTP **DELETE** (see
the center Integrations table), and POSTing either gives 405.

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

## Guarded resources: intakes and intake-agrupations

`centers/{c}/intakes` and `centers/{c}/intake-agrupations` can be switched on or
off in the center's configuration. If they are off, **warn but do not block** —
the caller may legitimately want to try.

Use `warnings.warn(..., UserWarning)`, not the logger: Python shows it by default
in a plain script without any logging setup, which is how these scripts are run.

The center config flags are on the center detail (`GET /installations/{i}/centers/{c}`):
**`use_intakes_association`** (intakes) and **`use_intakes_grouping`**
(intake-agrupations), both booleans. `use_families_for_productions` is a related
production flag. When either intakes flag is `False`, warn before hitting the
matching collection.

## Operations deliberately left out

- **`all-dictionaries/{id}/delete` is not implemented.** A dictionary must not be
  deleted casually; if someone really needs it, they do it from the web UI.
  Do not add it "for completeness".
- **Pill colours and shapes are read-only from this library.**
  `translations/search?context=medicine_pill_colors` and
  `...?context=medicine_pill_shapes` may be listed, but modifications go through
  the web UI.

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
  integration_providers(category)          -> /integration-providers/{category}/search
  integration_provider_form(provider_id)
  paper_rolls, paper_roll_uploads, translations, all_dictionaries,
  licenses, machine_models
  support_access_logs                      (super-admin only)

client.installation(i)
  details()                                -> /installations/{i}
  centers, cassettes, machines, trays, layouts, warehouses, fill_stations,
  medication_providers, users, medicines, medicine_families,
  medicines_families, productions
  .cassette(x)      -> medicines.add(), replenishes.add(), history
  .machine(m)       -> configuration, certificate, bases, fsps
  .tray(t)
  .fill_station(f)
  .user(u)          -> sessions, user_mobile_alerts
  .nurse(user_id)   -> shifts
  .production(p)    -> dose_takes, fsps, without_bags, save_to_machine(),
                       send_to_machine(), set_status()
  .center(c)
     patients, doctors, modules, intakes, intake_agrupations,
     imported_medicines, integrations
     update(), import_patients_and_treatments()
     .module(m)     -> submodules
     .patient(p)    -> treatments
```

`Installation` currently exposes `center(id)` but no `centers` collection — add
it, the plural/singular rule applies here too.

---

# Endpoint catalogue

The paths below are the target surface of the library. Ids in the examples are
real ones from the maintainer's environment (`{i}` = installation, `{c}` =
center). Entries marked *(verify)* were transcribed from browser traffic and have
not been confirmed against the API yet.

## Root

| Path | Notes |
|---|---|
| `/machine-models/search` | `query`, `itemsPerPage=1000`. **Not** admin-only, any user sees it |
| `/integration-providers/{category}/search` | providers a center can wire to. `category` is a path segment (see below). **Rejects any pagination param with a 500** — call it with an empty query string (`default_items_per_page=None`). Envelope counts in `max_results`, **not** `maxResults`. Each item has an `auth_form` |
| `/integration-providers/{id}/integration-provider-form` | the provider's `auth_form` on its own: `[{label,name,type,options,is_required}]` |

Integration-provider `category` values: `productions`, `patients-and-treatments`,
`medicines`, `order-delivery-clients`, `delivery-order-consumptions`,
`login-authentications`, `control-dose-take-administrations`, `sales`, `counters`,
`cassettes`. The first nine are the sections of a center's INTEGRATIONS tab.
| `/paper-rolls/search` | snake_case `items_per_page=10`, `page`. ~200k rows |
| `/paper-rolls/{id}` | e.g. `200261` |
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
| `/installations/{i}/machines` | |
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
| `/installations/{i}/medication-providers/search` | `itemsPerPage`, `page` |
| `/installations/{i}/medication-providers/create` | |
| `/installations/{i}/medication-providers/update` | observed **without an id** in the path — *(verify)*, it should be `/{id}/update` |

### Medicines and families

| Path | Notes |
|---|---|
| `/installations/{i}/medicines-families/search` | `is_active`, `is_family=true\|false`, `is_medicine`, `with_count`. `-1` is the default but is very slow |
| `/installations/{i}/medicines-families/medicines/{id}` | single medicine |
| `/installations/{i}/medicines/create` | |
| `/installations/{i}/medicines/{id}/update` | |
| `/installations/{i}/medicines/{id}/customize` | installation-level customisation |
| `/installations/{i}/medicines/{id}/community-characteristics` | |
| `/installations/{i}/centers/{c}/medicines/{id}/customized` | per-center view |
| `/installations/{i}/centers/{c}/medicines/{id}/customize` | per-center customisation |
| `/installations/{i}/medicine-families/create` | note the singular `medicine-` |
| `/installations/{i}/medicine-families/{id}/update` | |

### Productions

Low priority — the production module is huge and will barely be used.

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
| `/installations/{i}/centers/{c}/productions/{p}/medicine-families` | center-scoped |
| `/installations/{i}/centers/{c}/productions/{p}/production-filters` | center-scoped |
| `/installations/{i}/centers/{c}/productions/{p}/production-filters/update` | center-scoped |
| `/installations/{i}/centers/{c}/productions/{p}/update` | center-scoped |

### Already implemented, endpoint names unverified

`layouts`, `warehouses` — first-pass guesses. Confirm against the API.

## Center

| Path | Notes |
|---|---|
| `/installations/{i}/centers` | **bare JSON list**, no `/search`, no envelope. Confirmed |
| `/installations/{i}/centers/{c}` | center detail (object). Confirmed → `Center.details()` |
| `/installations/{i}/centers/{c}/update` | **PUT** (POST → 405), **partial body** accepted (merges) → `Center.update(**fields)` |
| `/installations/{i}/centers/{c}/import-patients-and-treatments` | action, **POST** (PUT → 405). Pulls from the center's supplier integration; none → 500 / `error_code` 87006 |
| `/installations/{i}/centers/{c}/patients/search` | implemented |
| `/installations/{i}/centers/{c}/intakes` | **guarded** — warn if disabled in the center config |
| `/installations/{i}/centers/{c}/intake-agrupations` | **guarded** — same |
| `/installations/{i}/centers/{c}/imported-medicines/search` | `itemsPerPage=-1`, `not_associated=true\|false` must be settable |
| `/installations/{i}/centers/{c}/doctors` | |
| `/installations/{i}/centers/{c}/doctors/{d}` | |
| `/installations/{i}/centers/{c}/doctors/create` | |

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

**This resource breaks the "writes are POST to a sub-path" rule.** Update is a
PUT and delete is an HTTP DELETE — POSTing either gives 405. Both return no body
(202/204), which is why `request()` returns `None` on empty content. There is no
hard delete.

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

| Path | Notes |
|---|---|
| `/installations/{i}/centers/{c}/modules` | |
| `/installations/{i}/centers/{c}/modules/create` | |
| `/installations/{i}/centers/{c}/modules/{m}/update` | |
| `/installations/{i}/centers/{c}/modules/{m}/submodules` | |
| `/installations/{i}/centers/{c}/modules/{m}/submodules/create` | |
| `/installations/{i}/centers/{c}/modules/{m}/submodules/{s}/update` | |
| `/installations/{i}/centers/{c}/modules/{m}/submodules/{s}/delete` | |

## Patient

| Path | Notes |
|---|---|
| `/installations/{i}/centers/{c}/patients/{p}/treatments/search` | implemented |
| `/installations/{i}/centers/{c}/patients/{p}/treatments/{t}` | implemented |

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
endpoints, query params and request bodies. It intercepts `**/api/**` and:

- **Mode A** — aborts every non-`GET` request. Nothing can be written, not even
  by accident while clicking around the SPA.
- **Mode B** — fills a create/update form, reads `request.post_data()`, and
  aborts the request anyway. You get the exact JSON body without the write ever
  reaching the server. The web UI will show a network error; that is expected.

Traffic goes to `artifacts/` (gitignored). Responses are recorded as **schema
only** — keys and types, never values — because they carry real patient data.

# Rules

- **Never commit credentials.** No passwords, tokens or `.env` contents in
  source, tests, comments or commit messages.
- **Never print full API payloads** in examples or debug output — they contain
  real patient data, pharmacy names and tax IDs. Print keys, counts, or
  truncated values (`token[:8]`).
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
storage, expiry check, authenticated `request()`/`get()`/`post()`), resource
scopes for installation / center / patient, installable package. `Root` scope
with integration providers. `BareListResource` for envelope-less collections.
Center integrations (`center.integrations`, with `create`/`update`/`delete`).
`Center.details()` / `update()` / `import_patients_and_treatments()`.

Not done yet:
- **Write operations.** `create()` / `update()` / `delete()` on `Resource`,
  following the `{resource}/create` POST convention above, plus the named action
  methods (`add`, `send-to-machine`, `import-patients-and-treatments`).
- **Non-JSON responses and file uploads.** `request()` always calls `.json()`;
  downloads and `multipart` CSV/TXT uploads need a path around it.
- **`Root` scope** (`resources/root.py`) exists but only wires integration
  providers; still to add: paper rolls, dictionaries, licenses, translations,
  machine models, support access logs.
- **Configurable pagination.** `items_per_page_param` and
  `default_items_per_page` as `Resource` class attributes.
- **`Installation.centers`** collection (only `center(id)` exists today).
- **The intakes / intake-agrupations warning**, once the center-config flag name
  is known.
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
