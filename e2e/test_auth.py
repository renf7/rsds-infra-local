"""Real browser -> OAuth boundary fixture -> Spring callback -> signed JWT -> DynamoDB.

No backend/session/JWT browser routes are intercepted. Only country lookup is mocked.
Live provider registration/consent/MFA remains a separate external acceptance check.
"""
import base64
import json
import os
from pathlib import Path
import time
import unittest
import xml.etree.ElementTree as ET
from playwright.sync_api import expect, sync_playwright

BASE_URL = os.environ['BASE_URL'].rstrip('/')
ARTIFACTS = Path('/artifacts')
PROVIDERS = ['facebook', 'microsoft', 'google', 'apple', 'github']
LABELS = {'github': 'GitHub'}


class AuthenticationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context()
        self.context.route('https://api.country.is/**', lambda route: route.fulfill(json={'country': 'US'}))
        self.page = self.context.new_page()
        self.page.set_default_timeout(5000)
        self.errors = []
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))

    def tearDown(self):
        self.page.screenshot(path=str(ARTIFACTS / (self._testMethodName + '.png')), full_page=True)
        self.context.close()
        self.assertFalse(self.errors, 'Browser runtime errors')

    def login(self, provider='google', choice='Continue as Alice', route='/'):
        self.page.goto(BASE_URL + route)
        self.page.get_by_role('button', name='Zaloguj się' if route.startswith('/pl/') else 'Log in', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        dialog.get_by_role('link', name=LABELS.get(provider, provider.capitalize()), exact=True).click()
        expect(self.page.get_by_role('heading', name=f'Local {provider} identity provider')).to_be_visible()
        self.page.get_by_role('button', name=choice, exact=True).click()

    def access_cookie(self):
        cookies = self.context.cookies()
        found = [cookie for cookie in cookies if cookie['name'] == 'RSDS_ACCESS']
        self.assertEqual(len(found), 1, 'A first-party JWT cookie must reach the browser')
        return found[0]

    def assert_authenticated(self, provider, language='en'):
        expect(self.page.get_by_role('button', name='Wyloguj' if language == 'pl' else 'Log out', exact=True)).to_be_visible()
        cookie = self.access_cookie()
        self.assertTrue(cookie['httpOnly'])
        self.assertEqual(cookie['sameSite'], 'Lax')
        self.assertEqual(len(cookie['value'].split('.')), 3)
        claims = json.loads(base64.urlsafe_b64decode(cookie['value'].split('.')[1] + '=='))
        self.assertEqual(claims['iss'], 'https://www.rsdsoftware.eu/auth')
        self.assertIn('rsds-infra', claims['aud'])
        self.assertGreater(claims['exp'], time.time())
        self.assertLessEqual(claims['exp'] - claims['iat'], 300)
        self.assertEqual(claims['roles'], [], 'Untrusted provider roles cannot grant application roles')
        self.assertNotIn('RSDS_ACCESS', self.page.evaluate('document.cookie'))
        self.assertNotIn(cookie['value'], self.page.url)
        self.assertEqual(self.page.evaluate('localStorage.getItem("access_token")'), None)
        response = self.context.request.get(BASE_URL + '/api/auth/me')
        self.assertEqual(response.status, 200, 'The backend must verify the actual signed JWT')
        identity = response.json()
        self.assertEqual(identity['provider'], provider)
        self.assertEqual(identity['subject'], claims['sub'])
        self.page.reload()
        expect(self.page.get_by_role('button', name='Wyloguj' if language == 'pl' else 'Log out', exact=True)).to_be_visible()

    def csrf(self):
        response = self.context.request.get(BASE_URL + '/api/auth/csrf')
        self.assertEqual(response.status, 200)
        return {'X-XSRF-TOKEN': response.json()['token']}

    def test_modal_keyboard_escape_and_focus_restoration(self):
        self.page.goto(BASE_URL + '/')
        button = self.page.get_by_role('button', name='Log in', exact=True)
        button.click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        for provider in PROVIDERS:
            expect(dialog.get_by_role('link', name=LABELS.get(provider, provider.capitalize()), exact=True)).to_be_visible()
        for _ in range(10):
            self.page.keyboard.press('Tab')
            self.assertTrue(dialog.evaluate('element => element.contains(document.activeElement)'), 'Modal must retain keyboard focus')
        self.page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        expect(button).to_be_focused()

    def test_logout_requires_csrf_and_clears_session(self):
        self.login()
        self.assert_authenticated('google')
        self.assertEqual(self.context.request.post(BASE_URL + '/api/auth/logout').status, 403)
        self.assertEqual(self.context.request.post(BASE_URL + '/api/auth/logout', headers=self.csrf()).status, 204)
        self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/me').status, 401)
        self.assertFalse(any(c['name'] == 'RSDS_ACCESS' for c in self.context.cookies()))

    def test_mobile_signed_in_controls_do_not_overflow(self):
        self.page.set_viewport_size({'width': 320, 'height': 700})
        self.login()
        self.assert_authenticated('google')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 320)

    def test_polish_sso_restores_the_language_route(self):
        self.login(route='/pl/')
        expect(self.page).to_have_url(BASE_URL + '/pl/?login=success')
        self.assert_authenticated('google', 'pl')

    def test_missing_state_rejected_without_jwt(self):
        response = self.context.request.get(BASE_URL + '/api/auth/login/oauth2/code/google?code=forged&state=forged', max_redirects=0)
        self.assertIn(response.status, [302, 400, 401])
        self.assertFalse(any(c['name'] == 'RSDS_ACCESS' for c in self.context.cookies()))

    def test_tampered_jwt_is_rejected(self):
        self.login()
        self.assert_authenticated('google')
        cookie = self.access_cookie()
        value = cookie['value']
        parts = value.split('.')
        parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
        cookie['value'] = '.'.join(parts)
        self.context.add_cookies([cookie])
        self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/me').status, 401)

    def test_refresh_rotates_and_replay_revokes_family(self):
        self.login()
        self.assert_authenticated('google')
        previous = next(c for c in self.context.cookies() if c['name'] == 'RSDS_REFRESH')
        self.assertEqual(self.context.request.post(BASE_URL + '/api/auth/refresh', headers=self.csrf()).status, 204)
        current = next(c for c in self.context.cookies() if c['name'] == 'RSDS_REFRESH')
        self.assertNotEqual(previous['value'], current['value'])
        self.context.add_cookies([previous])
        self.assertEqual(self.context.request.post(BASE_URL + '/api/auth/refresh', headers=self.csrf()).status, 401)
        self.context.add_cookies([current])
        self.assertEqual(self.context.request.post(BASE_URL + '/api/auth/refresh', headers=self.csrf()).status, 401)


def successful_login(provider):
    def test(self):
        self.login(provider)
        self.assert_authenticated(provider)
    return test


def rejected_login(provider, choice):
    def test(self):
        self.login(provider, choice)
        expect(self.page.get_by_role('button', name='Log in', exact=True)).to_be_visible()
        self.assertFalse(any(c['name'] == 'RSDS_ACCESS' for c in self.context.cookies()))
        expect(self.page.get_by_role('alert')).to_contain_text('Sign-in failed')
    return test


for provider in PROVIDERS:
    setattr(AuthenticationTests, f'test_{provider}_authorization_to_jwt', successful_login(provider))
    setattr(AuthenticationTests, f'test_{provider}_consent_denied', rejected_login(provider, 'Deny consent'))
for provider in ['google', 'microsoft', 'apple']:
    setattr(AuthenticationTests, f'test_{provider}_invalid_signature', rejected_login(provider, 'Invalid token signature'))


if __name__ == '__main__':
    ARTIFACTS.mkdir(exist_ok=True)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(AuthenticationTests))
    summary = {'browser': 'chromium', 'headless': True, 'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'passed': result.wasSuccessful() and result.testsRun >= 20, 'providerBoundary': 'local-protocol-fixture'}
    (ARTIFACTS / 'auth-results.json').write_text(json.dumps(summary, indent=2))
    suite = ET.Element('testsuite', tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)))
    for test, detail in result.failures + result.errors:
        ET.SubElement(ET.SubElement(suite, 'testcase', name=test.id()), 'failure').text = detail
    ET.ElementTree(suite).write(ARTIFACTS / 'auth-junit.xml', encoding='utf-8', xml_declaration=True)
    raise SystemExit(0 if summary['passed'] else 1)
