"""Capture what a real browser sees on the running build.

The ARIA snapshot lists roles, accessible names and text exactly as Playwright
locators will match them, which is what makes generated selectors real
instead of guessed.
"""
from __future__ import annotations

from playwright.sync_api import sync_playwright

MAX_SNAPSHOT_CHARS = 12000


def capture_aria_snapshot(url: str, *, timeout_ms: int = 20000) -> str:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            snapshot = page.locator("body").aria_snapshot(timeout=timeout_ms)
        finally:
            browser.close()
    if len(snapshot) > MAX_SNAPSHOT_CHARS:
        snapshot = snapshot[:MAX_SNAPSHOT_CHARS] + "\n[... snapshot truncated]"
    return snapshot
