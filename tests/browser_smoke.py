"""Optional real Chromium demo check: python tests/browser_smoke.py [base URL].

Install the test-only tool with `pip install playwright` and
`python -m playwright install chromium`; start a separate synthetic demo first.
No production/provider calls are needed. Screenshots go to the system temp dir.
"""
import sys
import re
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    output = Path(tempfile.mkdtemp(prefix="suraksha-browser-"))
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 1000}, service_workers="block")
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base)
        expect(page.locator("#mode-banner")).to_be_visible()
        expect(page.locator("#coverage-summary")).to_have_text("0 complete · 42 partial")
        expect(page.locator("#error-banner")).to_be_hidden()
        expect(page.locator("#hazard-coverage .coverage-item")).to_have_count(3)
        page.screenshot(path=str(output / "overview-desktop.png"), full_page=True)
        page.locator("#hazard-coverage .coverage-item").nth(2).get_by_role("button").click()
        expect(page.locator("#district-rows tr")).to_have_count(42)
        expect(page.locator("#result-count")).to_contain_text("missing selected hazard")
        page.locator("#search").fill("Pune")
        expect(page.locator("#district-rows tr")).to_have_count(1)
        page.locator("#district-rows").get_by_role("button", name="Pune", exact=True).click()
        expect(page.locator("#d-name")).to_have_text("Pune")
        expect(page.locator("#advisory")).to_contain_text("DEMO")
        expect(page.locator("#district-coverage tbody tr")).to_have_count(7)
        expect(page.locator("#district-coverage tbody tr").first).to_contain_text("Unknown")
        page.locator("#save-district").click()
        expect(page.locator("#save-district")).to_contain_text("Saved")
        page.locator("#language").select_option("hi")
        expect(page.locator("#d-name")).to_have_text("पुणे")
        page.locator("#language").select_option("en")
        expect(page.locator("#d-name")).to_have_text("Pune")
        # Force the server's no-TTS fallback so the result doesn't depend on edge-tts network reachability.
        page.route("**/voice?*", lambda route: route.fulfill(status=200, body="", headers={"X-TTS-Engine": "fallback"}))
        page.locator("#voice").click()
        expect(page.locator("#voice")).to_be_enabled(timeout=30000)
        expect(page.locator("#toast")).to_contain_text(re.compile("device|Voice unavailable", re.I), timeout=30000)
        page.unroute("**/voice?*")
        page.get_by_role("tab", name="Forecast", exact=True).click()
        expect(page.locator("#forecast-table tbody tr")).to_have_count(7)
        page.get_by_role("tab", name="History", exact=True).click()
        expect(page.locator("#history-table tbody tr")).to_have_count(14)
        page.get_by_role("tab", name="Mission brief", exact=True).click()
        expect(page.locator("#mission-content .timeline-cell")).to_have_count(7)
        # Capture the button's target and fetch its bytes with the browser context.
        page.evaluate("window.open = url => { window.exportTarget = url; }")
        page.locator("#csv").click()
        csv = context.request.get(base + page.evaluate("window.exportTarget"))
        assert csv.ok and "synthetic_demo" in csv.text() and "True" in csv.text()
        page.locator("#pdf").click()
        pdf = context.request.get(base + page.evaluate("window.exportTarget"))
        assert pdf.ok and pdf.body().startswith(b"%PDF")
        page.locator("#close-district").click()
        page.locator('[data-view="compare"]').click()
        for district in ("PUNE", "NAGPUR"):
            page.locator("#compare-picker").select_option(district)
            page.locator("#compare-add").click()
        expect(page.locator("#compare-results .compare-item")).to_have_count(2)
        page.locator('[data-view="preparedness"]').click()
        expect(page.locator("#checklist input").first).to_be_visible()
        page.locator("#checklist input").first.check()
        expect(page.locator("#check-progress")).to_contain_text("1 /")
        page.locator('[data-view="scenario"]').click()
        page.locator('[data-preset="rain"]').click()
        expect(page.locator("#scenario-results .mission-priority")).to_have_count(3)
        expect(page.locator("#scenario-results")).to_contain_text("rain_3day_mm: 260")
        page.locator("#open-chat").click()
        page.locator("#chat-input").fill("Pune advisory")
        page.locator("#chat-send").click()
        expect(page.locator("#chat-log .bot").last).to_contain_text("DEMO")
        page.locator("#close-chat").click()
        page.locator('[data-view="overview"]').click()
        context.set_offline(True)
        page.locator("#refresh").click()
        expect(page.locator("#error-banner")).to_be_visible()
        expect(page.locator("#map-coverage")).to_have_text("Scores unavailable")
        context.set_offline(False)
        page.locator("#refresh").click()
        expect(page.locator("#error-banner")).to_be_hidden()
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "Mobile page overflows horizontally"
        page.screenshot(path=str(output / "overview-mobile.png"), full_page=True)
        page.reload()
        expect(page.locator("#saved-count")).to_have_text("1")
        assert not errors, errors
        # A separate context permits the real PWA worker, unlike network-failure tests above.
        pwa = browser.new_context()
        shell = pwa.new_page()
        shell.goto(base)
        expect(shell.locator("#coverage-summary")).to_have_text("0 complete · 42 partial")
        shell.evaluate("navigator.serviceWorker.ready")
        shell.wait_for_function("navigator.serviceWorker.controller !== null")
        pwa.set_offline(True)
        shell.reload()
        expect(shell.locator("#page-title")).to_be_visible()
        expect(shell.locator("#error-banner")).to_be_visible(timeout=30000)
        expect(shell.locator("#district-rows")).not_to_contain_text("Pune")
        browser.close()
    print(f"Browser demo flows passed; desktop/mobile screenshots: {output}")


if __name__ == "__main__":
    main()
