"""Capture browser console and page errors as a Playwright fallback."""
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5173"
logs = []

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 900})
    page.on("console", lambda msg: logs.append(f"[{msg.type}] {msg.text}"))
    page.on("pageerror", lambda exc: logs.append(f"[pageerror] {exc}"))
    page.goto(URL, wait_until="domcontentloaded")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)
    browser.close()

with open("console.log", "w", encoding="utf-8") as output:
    output.write("\n".join(logs))
print(f"Captured {len(logs)} browser messages; wrote console.log")
