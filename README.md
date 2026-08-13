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

for installation in client.installations():
    print(installation["id"], installation["name"])
```

There is no separate login step — the first request authenticates, and later
requests re-authenticate once the token has expired.

## The hierarchy

Amco+ is strictly nested, and the library mirrors it as scopes:

```
installation (the pharmacy)
└── center (the care home it serves)
    └── patient
        └── treatments
```

```python
installation = client.installation(65)
center = installation.center(417)
patient = center.patient(3955)

print(installation.details()["name"])

for treatment in patient.treatments.list():
    print(treatment["id"])
```

Building a scope makes no request. Nothing hits the network until you call
something on a collection.

Two naming rules hold everywhere:

- **plural attribute = collection** — `center.patients`
- **singular method = one item** — `center.patient(3955)`

## Collections

Every collection has the same three methods:

```python
cassettes = installation.cassettes

cassettes.list()                       # every row, as a list
cassettes.list(is_active=True)         # filtered
cassettes.list(all_items=False, page=2)  # one page of 15
cassettes.search()                     # {"items": [...], "maxResults": N}
cassettes.get(57982)                   # a single cassette
```

`list()` asks for everything in one response (`itemsPerPage=-1`). That is
usually what you want, and why the client's default timeout is 120s rather than
httpx's 5s.

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
    print(exc.error_code, exc.error_message)
    # 1001 The installation <999999> does not exist
except AmcoError as exc:
    print(exc)  # "[9001] Credenciales invalidas | log_correlation_id: d176..."
```

`error_code` is Amco+'s own numeric code and is more reliable than the HTTP
status. Quote `log_correlation_id` when reporting a problem to Farmadosis.

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

Only a first pass of resources exists. For anything else, use the client
directly — the scope's path is public:

```python
centers = client.get("/installations/65/centers")
```

Watch the response shape when you do this. Most endpoints paginate under
`{resource}/search` and answer with `{"items": [...], "maxResults": N}`, but
`centers` is a plain list with no `/search` at all.

Writes (`create`, `update`, `delete`) are not implemented yet. Note that Amco+
does not use REST verbs: it writes with `POST` to `{resource}/create`,
`{resource}/{id}/update` and `{resource}/{id}/delete`.

`CLAUDE.md` holds the full catalogue of endpoints the library is working
towards, along with the API's quirks.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/test_manual.py
```

`scripts/test_manual.py` reads credentials from `.env` and hits the real API.
`.env` is gitignored; `.env.example` lists the variables.

Responses contain real patient data, pharmacy names and tax IDs. Never print a
full payload — print keys, counts or truncated values.
