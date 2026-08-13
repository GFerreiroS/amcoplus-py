"""Discover Amco+ API endpoints by driving the web UI through Playwright.

Development tool. Not part of the library.

Every request to the API is intercepted. GET requests pass through and their
response is recorded as a *schema* (keys and types, never values) because real
responses carry patient data. Everything that is not a GET is recorded and then
**aborted**, so no write can reach the server, not even by accident while
clicking around the SPA. Filling a create/update form and pressing save is
therefore safe: the request body is captured on its way out and the request
itself never leaves the browser. The UI will show a network error; that is the
expected outcome.

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

API_GLOB = "**/api/**"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MAX_REQUESTS_PER_SECOND = 20.0


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
    path = re.sub(r"/installations/\d+", "/installations/{i}", path)
    path = re.sub(r"/centers/\d+", "/centers/{c}", path)
    return re.sub(r"/\d+", "/{id}", path)


class Recorder:
    """Writes one JSON line per intercepted request."""

    def __init__(self, path: Path):
        self._file = path.open("a", encoding="utf-8")
        self.blocked = 0
        self.observed = 0

    def write(self, entry: dict) -> None:
        entry["at"] = datetime.now(timezone.utc).isoformat()
        self._file.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def make_handler(recorder: Recorder, throttle: Throttle):
    """Build the route handler that records traffic and blocks every write."""

    def handle(route: Route) -> None:
        request = route.request
        url = urlparse(request.url)
        entry = {
            "method": request.method,
            "path": url.path,
            "normalised_path": normalise_path(url.path),
            "query": {k: v for k, v in parse_qs(url.query, keep_blank_values=True).items()},
        }

        if request.method not in SAFE_METHODS:
            # Capture the body, then make sure the request never leaves.
            body = request.post_data
            if body:
                try:
                    entry["request_body"] = json.loads(body)
                except ValueError:
                    entry["request_body_raw"] = body[:4000]
            entry["blocked"] = True
            recorder.blocked += 1
            recorder.write(entry)
            print(f"  BLOCKED {request.method} {url.path}")
            route.abort("failed")
            return

        entry["blocked"] = False
        try:
            throttle.wait()  # only requests that actually leave are rate limited
            response = route.fetch()
            entry["status"] = response.status
            try:
                entry["response_schema"] = schema_of(response.json())
            except Exception:
                entry["response_schema"] = "<non-json>"
            route.fulfill(response=response)
        except Exception as exc:  # network hiccup, aborted navigation...
            entry["error"] = str(exc)[:200]
            try:
                route.continue_()
            except Exception:
                pass

        recorder.observed += 1
        recorder.write(entry)
        print(f"  {request.method} {url.path}")

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

    ARTIFACTS.mkdir(exist_ok=True)
    recorder = Recorder(TRAFFIC_FILE)
    throttle = Throttle(rate)

    print(f"Target: {web_url}")
    print(f"Rate limit: {rate:g} requests/second")
    print(f"Recording to: {TRAFFIC_FILE}\n")

    with sync_playwright() as playwright:
        # channel="chrome" reuses the Chrome already installed on this machine.
        browser = playwright.chromium.launch(headless=False, channel="chrome")
        context = browser.new_context(viewport={"width": 1600, "height": 950})
        page = context.new_page()
        page.route(API_GLOB, make_handler(recorder, throttle))

        page.goto(web_url)
        if login and password and try_login(page, login, password):
            print("Auto login attempted.")
        else:
            print("Log in manually in the browser window.")

        print(
            "\nRecording. Navigate the UI; open create/edit forms and save them —\n"
            "the body is captured and the request is blocked before it is sent.\n"
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
        record["params"].update(entry.get("query", {}))
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
    for (method, path), record in sorted(endpoints.items(), key=lambda item: item[0][1]):
        lines.append(
            f"| {method} | `{path}` | {record['count']} | "
            f"{', '.join(sorted(record['params'])) or '—'} | "
            f"{', '.join(sorted(record['body_keys'])) or '—'} |"
        )

    ARTIFACTS.mkdir(exist_ok=True)
    REPORT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {REPORT_FILE} ({len(endpoints)} endpoints)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="store_true", help="summarise recorded traffic")
    parser.add_argument(
        "--rate",
        type=float,
        default=MAX_REQUESTS_PER_SECOND,
        help=f"max requests per second (default {MAX_REQUESTS_PER_SECOND:g})",
    )
    args = parser.parse_args()
    report() if args.report else explore(args.rate)
