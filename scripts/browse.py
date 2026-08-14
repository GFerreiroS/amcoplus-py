"""Drive the Amco+ web UI from a script, with every write still blocked.

Companion to `explore_api.py`. That one records while a human clicks; this one
hands the clicking to a script, so a session can be walked step by step and
each step captured as a screenshot.

The same interception applies: writes are aborted, GETs are rate limited, and
traffic is appended to the same `artifacts/api-traffic.jsonl`.

The login is done once and the browser state is cached in
`artifacts/browser-state.json`, so later runs resume the session instead of
authenticating again.

Usage:
    from browse import session, shot

    with session() as page:
        page.goto(f"{page.web_url}/installations/117/centers/310")
        shot(page, "center-310")
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))

from explore_api import (  # noqa: E402
    API_GLOB,
    ARTIFACTS,
    MAX_REQUESTS_PER_SECOND,
    TRAFFIC_FILE,
    Recorder,
    Throttle,
    make_handler,
)

STATE_FILE = ARTIFACTS / "browser-state.json"
SHOTS = ARTIFACTS / "shots"


def shot(page, name: str) -> Path:
    """Screenshot the current page into `artifacts/shots/{name}.png`."""
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"  shot -> {path}", flush=True)
    return path


def log_in(page, web_url: str, login: str, password: str) -> None:
    """Authenticate if the session did not come back logged in already."""
    page.goto(web_url, wait_until="networkidle")
    password_box = page.locator("input[type=password]")
    if password_box.count() == 0:
        print("  already logged in", flush=True)
        return

    boxes = page.locator("input:not([type=password]):visible")
    boxes.first.fill(login)
    password_box.first.fill(password)
    password_box.first.press("Enter")
    page.wait_for_timeout(5000)
    print("  logged in", flush=True)


@contextmanager
def session(headless: bool = False, rate: float = MAX_REQUESTS_PER_SECOND):
    """Open a browser with writes blocked, yielding a ready-to-drive page."""
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    web_url = os.environ["AMCO_WEB_URL"].rstrip("/")
    login = os.environ["AMCO_TEST_LOGIN"]
    password = os.environ["AMCO_TEST_PASSWORD"]

    ARTIFACTS.mkdir(exist_ok=True)
    recorder = Recorder(TRAFFIC_FILE)
    throttle = Throttle(rate)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless, channel="chrome")
        context = browser.new_context(
            viewport={"width": 1600, "height": 950},
            storage_state=str(STATE_FILE) if STATE_FILE.exists() else None,
        )
        page = context.new_page()
        page.web_url = web_url  # convenience for callers
        page.route(API_GLOB, make_handler(recorder, throttle))

        try:
            log_in(page, web_url, login, password)
            yield page
        finally:
            try:
                context.storage_state(path=str(STATE_FILE))
            except Exception:
                pass
            try:
                context.close()
                browser.close()
            except Exception:
                pass
            recorder.close()
            print(
                f"  {recorder.observed} reads, {recorder.blocked} writes blocked, "
                f"{throttle.delayed} throttled",
                flush=True,
            )
