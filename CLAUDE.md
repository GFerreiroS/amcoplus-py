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
  layouts, trays, warehouses, label designs.
- **Center-level resources** belong to the residence: patients (and below them,
  treatments).

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
    ├── installation.py   # Installation scope + pharmacy-level resources
    └── center.py         # Center and Patient scopes + their resources
scripts/
└── test_manual.py        # integration script hitting the real API
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

## API conventions

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
`{"items": [...], "maxResults": N}`. Query params: `page`, `itemsPerPage`
(`-1` returns everything), plus resource-specific filters like `is_active`.
Sorting params (`sortDesc[]`, `mustSort`, `multiSort`) are optional and unused.

`itemsPerPage=-1` is the preferred approach — the API handles large responses
well. Because those requests can be slow, `AmcoClient` has a generous default
`timeout` (httpx defaults to 5s, which is too low here).

**Single item:** `{resource}/{id}`, no `/search`.

Example paths:
```
/installations/search
/installations/5/cassettes/search
/installations/5/centers/8/patients/search
/installations/5/centers/8/patients/3955/treatments/search
/installations/5/centers/8/patients/3955/treatments/2725144
```

**Error envelope:**
```json
{"error_code": 9001, "error_message": "Credenciales invalidas",
 "details": null, "server_number": "2", "log_correlation_id": "d176..."}
```
`error_code` is Amco+'s own numeric code and is more reliable than the HTTP
status. Known so far: **9001 = invalid credentials** (returned with HTTP 422).
Other codes are discovered as they appear — add a branch to `raise_for_error()`
and document it here.

## Adding a resource

Two steps:

```python
# 1. in resources/installation.py or resources/center.py
class Layouts(Resource):
    path = "layouts"

# 2. register it in the owning scope's __init__
self.layouts = Layouts(client, self._base_path)
```

`list()`, `search()` and `get()` come from `Resource` for free. Put it under
`Installation` if it belongs to the pharmacy, under `Center` if it belongs to
the residence.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python scripts/test_manual.py
```

Runtime dependency: `httpx` only. Dev: `python-dotenv`.

`scripts/test_manual.py` reads credentials from `.env` at the repo root and hits
the real API. `.env` is gitignored; `.env.example` documents the variables.

## Rules

- **Never commit credentials.** No passwords, tokens or `.env` contents in
  source, tests, comments or commit messages.
- **Never print full API payloads** in examples or debug output — they contain
  real patient data, pharmacy names and tax IDs. Print keys, counts, or
  truncated values (`token[:8]`).
- Keep `raise_for_error()` as the only place that maps responses to exceptions.
- Prefer adding a `Resource` subclass over writing raw `client.get()` calls.

## Status

Working: exception hierarchy, `raise_for_error()`, `AmcoClient` (login, token
storage, expiry check, authenticated `request()`/`get()`/`post()`), resource
scopes for installation / center / patient, installable package.

Not done yet:
- **Unit tests.** Deliberately deferred. When added, use `respx` to mock httpx
  and cover `raise_for_error()` branches, `is_token_valid()` edge cases (no
  token, just-expired, timezone handling) and re-login behaviour. Do not add
  tests that merely assert constructor assignments.
- **Automatic re-login on 401.** Retry exactly once, then fail — never loop.
- **Reusable `httpx.Client`** plus `close()` and context-manager support;
  currently each request opens a new connection.
- **Write operations** (`create`, `update`, `delete`) on `Resource`.
- **Logging** via a `logging.getLogger("amcoplus")` logger. Never log tokens or
  credentials.
- Most resource classes — only a first pass exists; verify actual endpoint names
  against the API before trusting them.
