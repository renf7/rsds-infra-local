"""Headless tests of the real Helm deployment; external country lookup is mocked."""

import json
import os
import re
from pathlib import Path
import sys
import time
import unittest
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ["BASE_URL"].rstrip("/")
ARTIFACTS = Path("/artifacts")


class SiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000}, locale="en-US")
        self.context.tracing.start(screenshots=True, snapshots=True, sources=True)
        self.errors = []
        self.country = "US"
        self.country_unavailable = False
        self.country_status = 200
        self.country_requests = 0
        self.context.route("**/*", self.route_request)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", self.record_console)
        self.page.on("response", self.record_response)
        self.page.on("requestfailed", self.request_failed)

    def route_request(self, route):
        target = urlsplit(route.request.url)
        if target.hostname == "api.country.is":
            self.country_requests += 1
            # Deterministic and offline: exercise country selection without calling a third party.
            if self.country_unavailable:
                route.fulfill(status=200, content_type="application/json", body="{}")
            else:
                route.fulfill(status=self.country_status, content_type="application/json", body=json.dumps({"country": self.country}))
        elif target.netloc == urlsplit(BASE_URL).netloc:
            route.continue_()
        else:
            self.errors.append(f"Unexpected external request: {route.request.url}")
            route.abort()

    def record_console(self, message):
        if message.type != "error":
            return
        # The failure scenario deliberately serves a 503 from this mock only.
        if self.country_status == 503 and message.location.get("url") == "https://api.country.is/" and "503" in message.text:
            return
        self.errors.append(message.text)

    def record_response(self, response):
        if response.status < 400:
            return
        if self.country_status == 503 and response.url == "https://api.country.is/" and response.status == 503:
            return
        self.errors.append(f"HTTP {response.status}: {response.url}")

    def request_failed(self, request):
        # Location.replace may intentionally cancel the superseded document request.
        if request.is_navigation_request() and request.failure == "net::ERR_ABORTED":
            return
        self.errors.append(f"Request failed: {request.url}: {request.failure}")

    def tearDown(self):
        try:
            self.page.screenshot(path=str(ARTIFACTS / f"{self._testMethodName}.png"), full_page=True)
            self.assertEqual([], self.errors, "Browser runtime/network errors")
        finally:
            self.context.tracing.stop(path=str(ARTIFACTS / f"{self._testMethodName}.zip"))
            self.context.close()

    def assert_page(self, language):
        expect(self.page.locator("html")).to_have_attribute("lang", language)
        expect(self.page).to_have_title(re.compile("RSD Software"))
        expect(self.page.locator("h1")).to_be_visible()
        expect(self.page.locator(f'[data-language-choice="{language}"]')).to_have_attribute("aria-current", "page")
        expect(self.page.locator('.brand img')).to_be_visible()
        self.assertTrue(self.page.locator('.brand img').evaluate("image => image.complete && image.naturalWidth > 0"))
        for section in ("java", "ai", "team", "services", "contact"):
            expect(self.page.locator(f"#{section} h2")).to_have_count(1)
        expect(self.page.locator('a[href="mailto:contact@rsdsoftware.eu"]')).to_be_visible()
        self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Horizontal overflow")

    def test_english_desktop_navigation(self):
        self.page.goto(BASE_URL + "/")
        self.assert_page("en")
        self.page.locator('.site-nav a[href="#services"]').click()
        expect(self.page).to_have_url(BASE_URL + "/#services")
        self.page.locator('.site-nav a[href="#contact"]').click()
        expect(self.page).to_have_url(BASE_URL + "/#contact")

    def test_polish_desktop_navigation(self):
        self.page.goto(BASE_URL + "/pl/")
        self.assert_page("pl")
        self.page.locator('.site-nav a[href="#contact"]').click()
        expect(self.page).to_have_url(BASE_URL + "/pl/#contact")

    def test_language_choice_persists_across_navigation_and_reload(self):
        self.page.goto(BASE_URL + "/")
        self.page.locator('[data-language-choice="pl"]').click()
        expect(self.page).to_have_url(BASE_URL + "/pl/")
        self.assertEqual("pl", self.page.evaluate('localStorage.getItem("rsd-language-preference")'))
        self.page.goto(BASE_URL + "/")
        expect(self.page).to_have_url(BASE_URL + "/pl/")
        self.page.locator('[data-language-choice="en"]').click()
        expect(self.page).to_have_url(BASE_URL + "/")
        self.page.reload()
        self.assert_page("en")
        self.assertEqual("en", self.page.evaluate('localStorage.getItem("rsd-language-preference")'))

    def test_polish_country_redirect_preserves_query_and_fragment(self):
        self.country = "PL"
        self.page.goto(BASE_URL + "/?source=e2e#services")
        expect(self.page).to_have_url(BASE_URL + "/pl/?source=e2e#services")
        expect(self.page.locator("html")).to_have_attribute("lang", "pl")

    def test_unknown_country_keeps_english_fallback(self):
        self.country_unavailable = True
        self.page.goto(BASE_URL + "/")
        self.assert_page("en")

    def test_mobile_pages_and_language_switch(self):
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.goto(BASE_URL + "/")
        self.assert_page("en")
        self.page.screenshot(path=str(ARTIFACTS / "mobile-en.png"), full_page=True)
        self.page.locator('[data-language-choice="pl"]').click()
        expect(self.page).to_have_url(BASE_URL + "/pl/")
        self.assert_page("pl")
        self.page.locator('.hero-actions a[href="#contact"]').click()
        expect(self.page).to_have_url(BASE_URL + "/pl/#contact")

    def test_all_section_links_ctas_and_brand_home(self):
        for route in ("/", "/pl/"):
            with self.subTest(route=route):
                self.page.goto(BASE_URL + route)
                for section in ("java", "ai", "team", "services", "contact"):
                    self.page.locator(f'.site-nav a[href="#{section}"]').click()
                    expect(self.page).to_have_url(BASE_URL + route + "#" + section)
                    expect(self.page.locator(f"#{section} h2")).to_be_in_viewport()
                self.page.locator(".brand").click()
                expect(self.page).to_have_url(BASE_URL + route)
                expect(self.page.locator("h1")).to_be_in_viewport()
                for section in ("services", "contact"):
                    self.page.locator(f'.hero-actions a[href="#{section}"]').click()
                    expect(self.page).to_have_url(BASE_URL + route + "#" + section)
                    expect(self.page.locator(f"#{section} h2")).to_be_in_viewport()

    def test_language_links_work_with_keyboard(self):
        self.page.goto(BASE_URL + "/")
        for language, route in (("pl", "/pl/"), ("en", "/")):
            link = self.page.locator(f'[data-language-choice="{language}"]')
            link.focus()
            expect(link).to_be_focused()
            self.page.keyboard.press("Enter")
            expect(self.page).to_have_url(BASE_URL + route)
            expect(self.page.locator("html")).to_have_attribute("lang", language)

    def test_responsive_navigation_breakpoint(self):
        self.page.goto(BASE_URL + "/")
        for width in (320, 390, 640, 641, 1024):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 900})
                java = self.page.locator('.site-nav a[href="#java"]')
                if width <= 640:
                    expect(java).to_be_hidden()
                else:
                    expect(java).to_be_visible()
                expect(self.page.locator(".site-nav .nav-cta")).to_be_visible()
                for language in ("en", "pl"):
                    expect(self.page.locator(f'[data-language-choice="{language}"]')).to_be_visible()
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow at {width}px")

    def test_saved_english_preference_overrides_polish_country(self):
        self.country = "PL"
        self.context.add_init_script('localStorage.setItem("rsd-language-preference", "en")')
        self.page.goto(BASE_URL + "/")
        self.assert_page("en")
        self.assertEqual(0, self.country_requests, "Saved preference should avoid country lookup")

    def test_saved_polish_preference_redirects_index_with_query_and_hash(self):
        self.context.add_init_script('localStorage.setItem("rsd-language-preference", "pl")')
        self.page.goto(BASE_URL + "/index.html?source=bookmark#team", wait_until="domcontentloaded")
        expect(self.page).to_have_url(BASE_URL + "/pl/?source=bookmark#team")
        expect(self.page.locator("html")).to_have_attribute("lang", "pl")
        self.assertEqual(0, self.country_requests)

    def test_cached_polish_country_redirects_without_lookup(self):
        self.context.add_init_script('sessionStorage.setItem("rsd-detected-country", "PL")')
        self.page.goto(BASE_URL + "/", wait_until="domcontentloaded")
        expect(self.page).to_have_url(BASE_URL + "/pl/")
        self.assertEqual(0, self.country_requests)

    def test_country_is_normalized_and_cached_across_english_entries(self):
        self.country = "us"
        self.page.goto(BASE_URL + "/")
        self.page.wait_for_function('sessionStorage.getItem("rsd-detected-country") === "US"')
        self.assertEqual(1, self.country_requests)
        self.page.goto(BASE_URL + "/index.html")
        self.assert_page("en")
        self.page.reload()
        self.assertEqual(1, self.country_requests, "Cached country should prevent repeat lookups")

    def test_direct_polish_route_ignores_english_preference(self):
        self.context.add_init_script('localStorage.setItem("rsd-language-preference", "en")')
        self.page.goto(BASE_URL + "/pl/")
        self.assert_page("pl")
        self.assertEqual(0, self.country_requests)
        self.assertEqual("en", self.page.evaluate('localStorage.getItem("rsd-language-preference")'))

    def test_storage_denied_still_allows_language_navigation(self):
        self.context.add_init_script("""for (const name of ['getItem', 'setItem']) {
            Storage.prototype[name] = () => { throw new DOMException('Storage blocked for test', 'SecurityError'); };
        }""")
        self.page.goto(BASE_URL + "/")
        self.assert_page("en")
        for language, route in (("pl", "/pl/"), ("en", "/")):
            self.page.locator(f'[data-language-choice="{language}"]').click()
            expect(self.page).to_have_url(BASE_URL + route)
            self.assert_page(language)

    def test_country_service_http_failure_keeps_english_usable(self):
        self.country_status = 503
        with self.page.expect_response(lambda response: response.url == "https://api.country.is/" and response.status == 503):
            self.page.goto(BASE_URL + "/")
        self.assert_page("en")
        self.assertEqual(1, self.country_requests)
        self.assertIsNone(self.page.evaluate('sessionStorage.getItem("rsd-detected-country")'))
        self.page.locator('.hero-actions a[href="#contact"]').click()
        expect(self.page).to_have_url(BASE_URL + "/#contact")


class ReportResult(unittest.TextTestResult):
    def startTest(self, test):
        super().startTest(test)
        self.started = time.monotonic()

    def stopTest(self, test):
        case = ET.SubElement(self.suite, "testcase", name=test.id(), time=f"{time.monotonic() - self.started:.3f}")
        for candidate, detail in self.failures + self.errors:
            if candidate == test:
                ET.SubElement(case, "failure").text = detail
        super().stopTest(test)


if __name__ == "__main__":
    ARTIFACTS.mkdir(exist_ok=True)
    ReportResult.suite = ET.Element("testsuite", name="headless-chromium")
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SiteTests)
    auth_enabled = os.environ.get('AUTH_E2E') == 'true'
    if auth_enabled:
        from test_auth import AuthenticationTests
        suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(AuthenticationTests))
    result = unittest.TextTestRunner(verbosity=2, resultclass=ReportResult).run(suite)
    summary = {"browser": "chromium", "headless": True, "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "passed": result.wasSuccessful() and result.testsRun > 0}
    summary['authenticationEnabled'] = auth_enabled
    if auth_enabled:
        summary['identityProviderMode'] = 'local-protocol-fixture'
    ReportResult.suite.attrib.update(tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)))
    ET.ElementTree(ReportResult.suite).write(ARTIFACTS / "junit.xml", encoding="utf-8", xml_declaration=True)
    (ARTIFACTS / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sys.exit(0 if summary["passed"] else 1)
