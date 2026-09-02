"""Discover controls after the page has booted."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5173"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")

    print(f"Title: {page.title()}")
    for i, button in enumerate(page.locator("button").all()):
        if button.is_visible():
            print(f"button[{i}]: {button.inner_text().strip()}")
    for field in page.locator("input, textarea, select").all():
        if field.is_visible():
            print(f"field: {field.get_attribute('id') or field.get_attribute('name') or '[unnamed]'}")

    page.screenshot(path="element-discovery.png", full_page=True)
    browser.close()
