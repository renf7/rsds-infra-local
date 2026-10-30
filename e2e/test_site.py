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
        self.context.route("**/*", self.route_request)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.page.on("console", lambda message: self.errors.append(message.text) if message.type == "error" else None)
        self.page.on("response", lambda response: self.errors.append(f"HTTP {response.status}: {response.url}") if response.status >= 400 else None)
        self.page.on("requestfailed", self.request_failed)

    def route_request(self, route):
        target = urlsplit(route.request.url)
        if target.hostname == "api.country.is":
            # Deterministic and offline: exercise country selection without calling a third party.
            if self.country_unavailable:
                route.fulfill(status=200, content_type="application/json", body="{}")
            else:
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"country": self.country}))
        elif target.netloc == urlsplit(BASE_URL).netloc:
            route.continue_()
        else:
            self.errors.append(f"Unexpected external request: {route.request.url}")
            route.abort()

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
    result = unittest.TextTestRunner(verbosity=2, resultclass=ReportResult).run(unittest.defaultTestLoader.loadTestsFromTestCase(SiteTests))
    summary = {"browser": "chromium", "headless": True, "tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors), "passed": result.wasSuccessful() and result.testsRun > 0}
    ReportResult.suite.attrib.update(tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)))
    ET.ElementTree(ReportResult.suite).write(ARTIFACTS / "junit.xml", encoding="utf-8", xml_declaration=True)
    (ARTIFACTS / "results.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    sys.exit(0 if summary["passed"] else 1)
