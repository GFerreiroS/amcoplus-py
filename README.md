# amcoplus

Python client for the [Amco+](https://amcoplusapi.farmadosis.com) API
(Farmadosis) — the pharmaceutical automation platform used by pharmacies,
hospitals and care homes.

Private library. Not published to PyPI.

## Install

```bash
pip install -e .
```

Requires Python 3.10+. The only runtime dependency is `httpx`.

## Quick start

```python
from amcoplus import AmcoClient

client = AmcoClient(login="user@example.com", password="...")

installations = client.installations()
print(f"Visible installations: {len(installations)}")
```

There is no separate login step — the first request authenticates, and later
requests re-authenticate once the token has expired.

## The hierarchy

Amco+ is conceptually nested, and the library mirrors that model as scopes:

```
installation (the pharmacy)
└── center (the care home it serves)
    └── patient
        └── treatments
```

```python
installation_id = ...
center_id = ...
patient_id = ...

installation = client.installation(installation_id)
center = installation.center(center_id)
patient = center.patient(patient_id)

print(sorted(installation.details()))  # field names only
print(sorted(patient.details()))  # field names only: patient data is sensitive

page = patient.treatments.search(all_items=False, page=1)
for treatment in page["items"]:
    print(treatment["id"])
```

Building a scope makes no request. Nothing hits the network until you call a
request method such as `details()`, `list()`, `search()` or `get()`.

Two naming rules hold everywhere:

- **plural attribute = collection** — `center.patients`
- **singular method = one item** — `center.patient(patient_id)`

## Collections

Search-backed collections have the same three methods:

```python
cassettes = installation.cassettes

cassettes.list()  # every row, as a list
cassettes.list(is_active=True)  # filtered
cassettes.list(all_items=False, page=2)  # one page of 15
cassettes.search()  # {"items": [...], "maxResults": N}
cassettes.get(cassette_id)  # a single cassette
```

For these collections, `list()` asks for everything in one response
(`itemsPerPage=-1`). That is usually what you want, and why the client's default
timeout is 120s rather than httpx's 5s. Patients and treatments are the
exception in examples: use `search(all_items=False, page=N)` to avoid loading
unbounded clinical data.

Some collections return a bare list with no `/search` endpoint. Centers and the
lookups used by the center form are examples: `list()` calls the collection
path directly and `search()` is unavailable.

```python
centers = installation.centers.list()
one_center = installation.centers.get(center_id)

countries = client.root.countries.list()
production_layouts = installation.production_layouts.list()
production_sorts = installation.production_sorts.list()
machines = installation.machines.list()
```

A third shape returns a pagination envelope directly from the collection path,
without `/search`. `DirectResource` handles it; patient sales and holiday
periods are examples:

```python
sales_page = patient.sales.search(all_items=False, page=1)
holiday_page = patient.holiday_periods.search(
    all_items=False,
    page=1,
    itemsPerPage=15,
)
```

**Filters are per resource, and unknown ones are ignored rather than
rejected.** A typo in a filter name gives you unfiltered results, not an error.
Check the resource class docstring for what it accepts:

```python
help(installation.cassettes)
```

## Errors

Everything raises a subclass of `AmcoError`:

```python
from amcoplus import AmcoError, NotFoundError

try:
    client.installation(999999).cassettes.list()
except NotFoundError as exc:
    print(type(exc).__name__, exc.error_code, exc.log_correlation_id)
except AmcoError as exc:
    print(type(exc).__name__, exc.error_code, exc.log_correlation_id)
```

`error_code` is Amco+'s own numeric code and is more reliable than the HTTP
status. Quote `log_correlation_id` when reporting a problem to Farmadosis.
Server messages and `details` may echo sensitive request context, so inspect
them deliberately rather than writing `str(exc)` to shared logs.

Do not assume a missing row gives you `NotFoundError`. Asking for a cassette id
that does not exist returns HTTP 500 with an HTML body, which surfaces as
`APIError("Non-JSON error response (HTTP 500)")`. Catch `AmcoError` if you need
to be safe.

## On-premise deployments

Amco+ is also installed on-premise in hospitals and prisons, often without
internet access and with a self-signed certificate:

```python
client = AmcoClient(
    login="user@example.com",
    password="...",
    base_url="https://amco.hospital.local/api",
    verify_ssl=False,  # only for self-signed certificates
)
```

`verify_ssl=False` makes httpx warn on every request. That is intentional.

## Endpoints not covered yet

Only a first pass of resources exists. For an endpoint that has not been mapped
yet, you can still use the client directly:

```python
machine_models = client.get(
    "/machine-models/search",
    params={"itemsPerPage": 1000},
)
```

Watch the response shape when you do this. Most endpoints paginate under
`{resource}/search` and answer with `{"items": [...], "maxResults": N}`, but
`centers` is a plain list with no `/search` at all.

Writes are available only on resources whose routes and bodies have been mapped
as documented; some were accepted dynamically and others are SPA-observed.
Amco+ uses named subpaths with mixed HTTP methods: `POST {resource}/create`,
`PUT {resource}/{id}/update` and `DELETE {resource}/{id}/delete`. Not every
resource supports all three operations; check its class docstring.

`CLAUDE.md` holds the full catalogue of endpoints the library is working
towards, along with the API's quirks.

## Patient records

The patient scope mirrors the Information, Clinical data, Sales and Takes tabs.
Mobile alerts are documented in `CLAUDE.md` but intentionally have no public
API.

```python
from datetime import date

installation_id = ...
center_id = ...
patient_id = ...

patient = client.installation(installation_id).center(center_id).patient(patient_id)

details = patient.details()
diagnoses = patient.diagnoses.search(all_items=False, page=1, is_active=True)
sales = patient.sales.search(all_items=False, page=1)
takes = patient.dose_takes.search(date_at=date.today(), page=1)

treatment_page = patient.treatments.search(all_items=False, page=1)
if treatment_page["items"]:
    treatment_id = treatment_page["items"][0]["id"]
    with_configs = patient.treatment(treatment_id).with_configs()
```

Patients and treatments also have a direct bare-list GET, exposed explicitly as
`direct_list()`. Prefer `/search` for normal use because its total and page
shape are consistent and clinical data stays bounded.

The beta API does not enforce every parent segment of a nested item URL. Patient
scopes therefore validate the detail's `id` and `center_id`; child item actions
also require the ID to occur in that patient's collection. Treatments preflight
their own `patient_id` and discard a mismatch. These checks prevent accidental
cross-scope combinations but are not a substitute for atomic backend
authorization. Always derive child IDs from the same patient's list.

The exceptional global lookup is named `client.root.unscoped_treatment()` and
requires the explicit `allow_unscoped=True` opt-in.

Patient writes mirror the current web form. `patient.update(record)` and
`patient.treatment(id).update(record)` expect complete edited objects, not
assumed partial patches. Treatment writes require the explicit `configs` list;
the SDK rejects conflicting treatment/config ids and pins their parent ids.
Treatments on 2FA-enabled centers accept the optional `authenticate_code` and
`step_up_grant` keyword arguments. Attachment downloads return bytes and never
write a file automatically.

Use `client.send_two_factor_code()` or the step-up challenge/verify methods to
obtain those short-lived credentials. Sending a two-factor code has a real
external side effect; codes and grants are secrets and must not be logged.

Dose-take mark/reject actions require the control snapshot returned by the same
patient scope's `dose_takes.search()` or trusted bag lookup. Mark/reject/
simulate calls, treatment reviews, imports and sales-line updates are real,
auditable mutations. They are available as explicit methods but are
deliberately absent from read-only examples.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/test_manual.py
```

`scripts/test_manual.py` reads credentials from `.env` and hits the real API.
`.env` is gitignored; `.env.example` lists the variables.

`scripts/centers.py` contains read-only examples for the center hierarchy. Pass
only an installation id to list its centers, or add a center id to inspect its
nested resources:

```bash
python scripts/centers.py INSTALLATION_ID
python scripts/centers.py INSTALLATION_ID --configuration-lookups
python scripts/centers.py INSTALLATION_ID --center-id CENTER_ID
python scripts/centers.py INSTALLATION_ID --center-id CENTER_ID \
    --resources
python scripts/centers.py INSTALLATION_ID --center-id CENTER_ID \
    --patient-id PATIENT_ID --module-id MODULE_ID --medicine-id MEDICINE_ID
```

Apart from authentication, the script sends only GET requests and prints
counts, IDs and field names — never full API rows, which can contain personal
or clinical data. Integration rows may carry stored credentials, so that
example runs only when `--include-integrations` is passed explicitly. The
script never executes mutating methods.

`scripts/patients_and_treatments.py` is the focused read-only tour. Every
section must be selected explicitly. Paginated searches request one page;
bare/direct routes that offer no proven pagination are limited in output.
Detail calls print field names rather than patient, clinical, medication or
sales values:

```bash
python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID --patients
python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
    --patient-id PATIENT_ID --card
python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
    --patient-id PATIENT_ID --clinical --sales
python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
    --patient-id PATIENT_ID --treatments --treatment-id TREATMENT_ID
python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID \
    --patient-id PATIENT_ID --takes-date YYYY-MM-DD
python scripts/patients_and_treatments.py INSTALLATION_ID CENTER_ID --lookups
```

The script does not expose free-text query arguments, follow the electronic
prescription handoff or access mobile alerts. Apart from authentication, it
does not execute any POST/PUT/DELETE.

Responses contain real patient data, pharmacy names and tax IDs. Never print a
full payload: use field names, counts or non-secret internal IDs. Never print
even fragments of tokens, passwords, authentication codes or grants.
