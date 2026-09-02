"""Smoke-test an HTTP-delivered static page with Playwright.

Use the real deployment URL when possible; do not replace it with file:// when
checking Session Site routing or module MIME behavior.
"""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8765/files/ws/sessions/<session_id>/site/index.html"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    errors = []
    page.on("pageerror", lambda exc: errors.append(str(exc)))
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    page.screenshot(path="session-site-smoke.png")
    assert page.title(), "Expected a document title"
    assert page.locator("body").count() == 1
    assert not errors, f"Page errors: {errors}"
    browser.close()

print("HTTP static-page smoke test passed")
