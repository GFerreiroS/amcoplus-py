"""Discover Amco+ API endpoints by driving the web UI through Playwright.

Development tool. Not part of the library.

Every request to the API is intercepted. Ordinary GET responses are recorded as
a *schema* (keys and types, never values) because real responses carry patient
data. Known identifier path segments, query parameters and bodies are redacted
to route-like paths, parameter names and schemas. Mutating HTTP methods and known
side-effecting GET routes are recorded and then **aborted**. Unknown GET routes
still require judgment — HTTP GET alone is not proof that an endpoint has no
side effects.

Usage:
    python scripts/explore_api.py            # open the browser and record
    python scripts/explore_api.py --report   # summarise what was recorded
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv
from playwright.sync_api import Route, sync_playwright

ARTIFACTS = Path(__file__).resolve().parent.parent / "artifacts"
TRAFFIC_FILE = ARTIFACTS / "api-traffic.jsonl"
REPORT_FILE = ARTIFACTS / "endpoints-report.md"

API_GLOB = "**/api/**"  # compatibility for the local browse helper
ALL_URLS_GLOB = "**/*"
API_PATH_PREFIX = "/api/"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_REQUESTS_PER_SECOND = 20.0

SIDE_EFFECT_GET_PATTERNS = (
    re.compile(r"/two-factor/send$"),
    re.compile(r"/installations/\d+/ws-treatment$"),
    re.compile(r"/all-dictionaries/\d+/medicine-families/export-csv-file$"),
    re.compile(r"/all-dictionaries/\d+/medicines/export-csv-file$"),
)
"""Known GET routes that send messages, export mail, or may synchronize data."""

AUTH_PATHS = ("/api/login", "/api/refresh-token")
"""The only non-GET requests allowed through.

Authentication is a POST, so blocking every write indiscriminately means you
can never log in. These endpoints change no pharmacy data — they hand out a
token — so letting them past does not weaken the guarantee that matters.
"""


def is_write(method: str, path: str) -> bool:
    """Whether this request would modify data, and must therefore be blocked."""
    normalized_path = path.rstrip("/")
    if method in {"GET", "HEAD"} and any(
        pattern.search(normalized_path) for pattern in SIDE_EFFECT_GET_PATTERNS
    ):
        return True
    if method in SAFE_METHODS:
        return False
    return not (method == "POST" and normalized_path in AUTH_PATHS)


class Throttle:
    """Cap how fast requests reach the API.

    A single screen of the SPA can fan out into a burst of parallel calls, so
    this holds them back. The guarantee is a sliding window: no more than
    `max_per_second` requests in **any** one-second interval.

    Spacing requests evenly instead would not be equivalent — 20 requests a
    second apart by 1/20s still puts 21 of them inside some one-second window.
    """

    WINDOW = 1.0

    def __init__(self, max_per_second: float) -> None:
        self._max = max(1, int(max_per_second))
        self._lock = threading.Lock()
        self._sent: deque[float] = deque()
        self.delayed = 0

    def wait(self) -> None:
        with self._lock:
            while True:
                now = time.monotonic()
                while self._sent and now - self._sent[0] >= self.WINDOW:
                    self._sent.popleft()

                if len(self._sent) < self._max:
                    self._sent.append(now)
                    return

                # Window is full: sleep until its oldest entry falls out.
                self.delayed += 1
                time.sleep(max(self.WINDOW - (now - self._sent[0]), 0.001))


# --- recording -------------------------------------------------------------


def schema_of(value, depth: int = 0):
    """Describe the shape of a JSON value without keeping any of its data.

    Responses contain real patient names, pharmacy tax ids and so on, so only
    keys and type names are ever written to disk.
    """
    if depth > 6:
        return "..."
    if isinstance(value, dict):
        return {key: schema_of(item, depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        if not value:
            return ["<empty>"]
        return [schema_of(value[0], depth + 1)]
    if value is None:
        return "null"
    return type(value).__name__


def normalise_path(path: str) -> str:
    """Replace numeric path segments with placeholders so paths can be grouped."""
    path = re.sub(
        r"/[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}(?=/|$)",
        "/{uuid}",
        path,
    )
    path = re.sub(r"/find-with-chip/[^/]+", "/find-with-chip/{chip}", path)
    path = re.sub(r"/find-by-uuid/[^/]+", "/find-by-uuid/{uuid}", path)
    path = re.sub(r"/bags/[^/]+", "/bags/{bag}", path)
    path = re.sub(r"/mobile-device/[^/]+", "/mobile-device/{device}", path)
    path = re.sub(r"/installations/\d+", "/installations/{i}", path)
    path = re.sub(r"/centers/\d+", "/centers/{c}", path)
    return re.sub(r"/\d+", "/{id}", path)


class Recorder:
    """Writes one JSON line per intercepted request."""

    def __init__(self, path: Path):
        self._file = path.open("a", encoding="utf-8")
        path.chmod(0o600)
        self.blocked = 0
        self.observed = 0

    def write(self, entry: dict) -> None:
        entry["at"] = datetime.now(timezone.utc).isoformat()
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def make_handler(
    recorder: Recorder,
    throttle: Throttle,
    allowed_origins: frozenset[str] | None = None,
):
    """Record API traffic and block mutations across the browser context."""

    def handle(route: Route) -> None:
        request = route.request
        url = urlparse(request.url)
        safe_path = normalise_path(url.path)
        origin = f"{url.scheme}://{url.netloc}"
        is_allowed_origin = allowed_origins is None or origin in allowed_origins
        looks_like_api = API_PATH_PREFIX in url.path

        if looks_like_api and not is_allowed_origin:
            recorder.blocked += 1
            recorder.write(
                {
                    "method": request.method,
                    "path": safe_path,
                    "normalised_path": safe_path,
                    "untrusted_api_origin": True,
                    "blocked": True,
                }
            )
            print(
                f"  BLOCKED untrusted API origin {request.method} {safe_path}",
                flush=True,
            )
            route.abort("failed")
            return

        if not looks_like_api:
            if request.method not in SAFE_METHODS:
                recorder.blocked += 1
                recorder.write(
                    {
                        "method": request.method,
                        "path": safe_path,
                        "normalised_path": safe_path,
                        "external": True,
                        "blocked": True,
                    }
                )
                print(f"  BLOCKED external {request.method} {safe_path}", flush=True)
                route.abort("failed")
                return
            route.continue_()
            return

        entry = {
            "method": request.method,
            "path": safe_path,
            "normalised_path": safe_path,
            "query_keys": sorted(parse_qs(url.query, keep_blank_values=True)),
        }

        if is_write(request.method, url.path):
            # Capture only its schema, then make sure the request never leaves.
            body = request.post_data
            if body:
                try:
                    parsed_body = json.loads(body)
                    entry["request_body_schema"] = schema_of(parsed_body)
                    if isinstance(parsed_body, dict):
                        entry["body_keys"] = sorted(parsed_body)
                except ValueError:
                    entry["request_body_schema"] = "<non-json>"
            entry["blocked"] = True
            recorder.blocked += 1
            recorder.write(entry)
            print(f"  BLOCKED {request.method} {safe_path}", flush=True)
            route.abort("failed")
            return

        entry["blocked"] = False
        is_auth = url.path.rstrip("/") in AUTH_PATHS
        try:
            throttle.wait()  # only requests that actually leave are rate limited
            # Let the browser issue redirects as new requests so the context
            # handler re-checks their origin, method and side-effect denylist.
            response = route.fetch(max_redirects=0)
            entry["status"] = response.status
            if is_auth:
                # Never touch the login exchange: the request carries the
                # password and the response carries the access token.
                entry["auth"] = True
            else:
                try:
                    entry["response_schema"] = schema_of(response.json())
                except Exception:
                    entry["response_schema"] = "<non-json>"
            route.fulfill(response=response)
        except Exception as exc:  # network hiccup, aborted navigation...
            entry["error_type"] = type(exc).__name__
            try:
                route.continue_()
            except Exception:
                pass

        recorder.observed += 1
        recorder.write(entry)
        print(f"  {request.method} {safe_path}", flush=True)

    return handle


# --- session ---------------------------------------------------------------


def try_login(page, login: str, password: str) -> bool:
    """Best-effort auto login. Returns False so the operator can do it by hand."""
    candidates = [
        ("input[type=email]", "input[type=password]"),
        ("input[name=login]", "input[name=password]"),
        ("input[name=email]", "input[name=password]"),
    ]
    for user_selector, password_selector in candidates:
        try:
            page.fill(user_selector, login, timeout=3000)
            page.fill(password_selector, password, timeout=3000)
            page.keyboard.press("Enter")
            page.wait_for_timeout(4000)
            return True
        except Exception:
            continue
    return False


def explore(rate: float = MAX_REQUESTS_PER_SECOND) -> None:
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    web_url = os.environ.get("AMCO_WEB_URL")
    if not web_url:
        sys.exit("AMCO_WEB_URL is not set. Add the test environment URL to .env")

    login = os.environ.get("AMCO_TEST_LOGIN", "")
    password = os.environ.get("AMCO_TEST_PASSWORD", "")
    configured_origins = {web_url}
    if api_url := os.getenv("AMCO_BASE_URL"):
        configured_origins.add(api_url)
    allowed_origins = frozenset(
        f"{parsed.scheme}://{parsed.netloc}"
        for value in configured_origins
        if (parsed := urlparse(value)).scheme and parsed.netloc
    )

    ARTIFACTS.mkdir(mode=0o700, exist_ok=True)
    ARTIFACTS.chmod(0o700)
    recorder = Recorder(TRAFFIC_FILE)
    throttle = Throttle(rate)

    print(f"Target: {web_url}")
    print(f"Rate limit: {rate:g} requests/second")
    print(f"Recording to: {TRAFFIC_FILE}\n")

    with sync_playwright() as playwright:
        # channel="chrome" reuses the Chrome already installed on this machine.
        browser = playwright.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context(
            viewport={"width": 1600, "height": 950},
            service_workers="block",
        )
        context.route(
            ALL_URLS_GLOB,
            make_handler(recorder, throttle, allowed_origins),
        )
        page = context.new_page()

        page.goto(web_url)
        if login and password and try_login(page, login, password):
            print("Auto login attempted.")
        else:
            print("Log in manually in the browser window.")

        print(
            "\nRecording. Navigate the UI; open create/edit forms and save them —\n"
            "the body schema is captured; the request is blocked before it is "
            "sent.\n"
            "Close the browser window when you are done.\n"
        )

        # Stay alive until the window is closed, so this can run unattended in
        # the background while someone drives the browser.
        finished = threading.Event()
        page.on("close", lambda _: finished.set())
        browser.on("disconnected", lambda _: finished.set())
        try:
            while not finished.is_set():
                page.wait_for_timeout(500)
        except (KeyboardInterrupt, Exception):
            pass

        try:
            context.close()
            browser.close()
        except Exception:
            pass

    recorder.close()
    print(
        f"\n{recorder.observed} reads recorded, {recorder.blocked} writes blocked, "
        f"{throttle.delayed} throttled."
        f"\nTraffic: {TRAFFIC_FILE}"
    )


# --- report ----------------------------------------------------------------


def report() -> None:
    if not TRAFFIC_FILE.exists():
        sys.exit(f"No traffic recorded yet ({TRAFFIC_FILE} does not exist)")

    endpoints: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"count": 0, "params": set(), "body_keys": set(), "statuses": set()}
    )
    for line in TRAFFIC_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        key = (entry["method"], entry["normalised_path"])
        record = endpoints[key]
        record["count"] += 1
        record["params"].update(entry.get("query_keys", entry.get("query", {})))
        record["body_keys"].update(entry.get("body_keys", []))
        if isinstance(entry.get("request_body"), dict):
            record["body_keys"].update(entry["request_body"])
        if "status" in entry:
            record["statuses"].add(entry["status"])

    lines = [
        "# Discovered endpoints",
        "",
        f"From `{TRAFFIC_FILE.name}` — {len(endpoints)} distinct endpoints.",
        "",
        "| Method | Path | Hits | Query params | Body keys |",
        "|---|---|---|---|---|",
    ]
    for (method, path), record in sorted(
        endpoints.items(), key=lambda item: item[0][1]
    ):
        lines.append(
            f"| {method} | `{path}` | {record['count']} | "
            f"{', '.join(sorted(record['params'])) or '—'} | "
            f"{', '.join(sorted(record['body_keys'])) or '—'} |"
        )

    ARTIFACTS.mkdir(mode=0o700, exist_ok=True)
    ARTIFACTS.chmod(0o700)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    REPORT_FILE.chmod(0o600)
    print(f"Wrote {REPORT_FILE} ({len(endpoints)} endpoints)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report", action="store_true", help="summarise recorded traffic"
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=MAX_REQUESTS_PER_SECOND,
        help=f"max requests per second (default {MAX_REQUESTS_PER_SECOND:g})",
    )
    args = parser.parse_args()
    report() if args.report else explore(args.rate)
