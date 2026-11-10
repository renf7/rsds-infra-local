"""Real browser -> OAuth boundary fixture -> Spring callback -> signed JWT -> DynamoDB.

No backend/session/JWT browser routes are intercepted. Only country lookup is mocked.
Live provider registration/consent/MFA remains a separate external acceptance check.
"""
import base64
import json
import os
from pathlib import Path
import time
import re
import uuid
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
        field = self.page.locator('#auth-verification')
        if field.count() and field.is_visible():
            field.fill('')  # Never retain a submitted one-time code in a failure screenshot.
        self.page.screenshot(path=str(ARTIFACTS / (self._testMethodName + '.png')), full_page=True)
        self.context.close()
        self.assertFalse(self.errors, 'Browser runtime errors')

    def login(self, provider='google', choice='Continue as Alice', route='/', complete=True):
        self.page.goto(BASE_URL + route)
        self.page.get_by_role('button', name='Zaloguj się' if route.startswith('/pl/') else 'Log in', exact=True).click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        dialog.get_by_role('link', name=('Kontynuuj z ' if route.startswith('/pl/') else 'Continue with ') + LABELS.get(provider, provider.capitalize()), exact=True).click()
        expect(self.page.get_by_role('heading', name=f'Local {provider} identity provider')).to_be_visible()
        self.page.get_by_role('button', name=choice, exact=True).click()
        if complete:
            expect(self.page).to_have_url(re.compile(r'.*[?&]login=(success|verify|failed)'))
            self.assertNotIn('login=verify', self.page.url)
            expect(self.page.get_by_role('dialog')).not_to_be_visible()

    def latest_code(self):
        # Local SMTP fixture only: never write message bodies/codes into reports or traces.
        for _ in range(30):
            response = self.context.request.get(BASE_URL + '/__test/mail/api/v1/messages')
            if response.ok:
                messages = response.json().get('messages', [])
                if messages:
                    detail = self.context.request.get(BASE_URL + '/__test/mail/api/v1/message/' + messages[0]['ID']).json()
                    match = re.search(r'code is: ([0-9]{6})', detail.get('Text', ''))
                    if match:
                        return match.group(1)
            time.sleep(0.1)
        raise AssertionError('No verification message delivered to the local SMTP sink')

    def complete_email_verification(self, polish=False):
        field = self.page.get_by_label('Kod weryfikacyjny' if polish else 'Verification code', exact=True)
        expect(field).to_be_visible()
        field.fill(self.latest_code())
        self.page.get_by_role('button', name='Potwierdź i kontynuuj' if polish else 'Verify and continue', exact=True).click()
        expect(self.page.get_by_test_id('account-avatar')).to_be_visible()

    def access_cookie(self):
        cookies = self.context.cookies()
        found = [cookie for cookie in cookies if cookie['name'] == 'RSDS_ACCESS']
        self.assertEqual(len(found), 1, 'A first-party JWT cookie must reach the browser')
        return found[0]

    def assert_authenticated(self, provider, language='en'):
        avatar = self.page.get_by_test_id('account-avatar')
        expect(avatar).to_be_visible()
        expect(avatar).to_have_attribute('aria-haspopup', 'menu')
        expect(self.page.get_by_role('button', name='Wyloguj' if language == 'pl' else 'Log out', exact=True)).to_have_count(0)
        self.assertEqual(len(avatar.inner_text()), 2)
        self.assertEqual(avatar.inner_text(), avatar.inner_text().upper())
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
        self.assertNotIn('email', claims, 'Internal JWTs must not contain provider/contact email')
        self.assertNotIn('RSDS_ACCESS', self.page.evaluate('document.cookie'))
        self.assertNotIn(cookie['value'], self.page.url)
        self.assertEqual(self.page.evaluate('localStorage.getItem("access_token")'), None)
        response = self.context.request.get(BASE_URL + '/api/auth/me')
        self.assertEqual(response.status, 200, 'The backend must verify the actual signed JWT')
        identity = response.json()
        self.assertIn('email', identity)
        self.assertEqual(identity['subject'], claims['sub'])
        self.page.reload()
        expect(self.page.get_by_test_id('account-avatar')).to_be_visible()

    def csrf(self):
        response = self.context.request.get(BASE_URL + '/api/auth/csrf')
        self.assertEqual(response.status, 200)
        return {'X-XSRF-TOKEN': response.json()['token']}

    def test_shared_spinner_tracks_provider_navigation_settings_save_and_logout(self):
        # Delay transport only; real endpoints, JWT and database remain untouched.
        network = self.context.new_cdp_session(self.page)
        network.send('Network.enable')
        network.send('Network.emulateNetworkConditions', {'offline': False, 'latency': 800, 'downloadThroughput': 1000000, 'uploadThroughput': 1000000})
        self.page.goto(BASE_URL + '/')
        self.page.get_by_role('button', name='Log in', exact=True).click()
        spinner = self.page.get_by_test_id('activity-indicator')
        expect(spinner).to_be_visible()
        expect(spinner).not_to_be_visible()
        # Locator assertions wait for a pending navigation. Inspect the departing
        # document within its paint frame instead, before the delayed redirect.
        visible = self.page.evaluate("""async () => {
            document.querySelector('a[href="/api/auth/oauth2/authorization/google"]').click();
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            const indicator = document.querySelector('[data-testid="activity-indicator"]');
            return !!indicator && indicator.getBoundingClientRect().width > 0;
        }""")
        self.assertTrue(visible, 'Provider navigation must paint the shared spinner before leaving')
        screenshot = network.send('Page.captureScreenshot', {'format': 'png'})
        (ARTIFACTS / 'provider-navigation-spinner.png').write_bytes(base64.b64decode(screenshot['data']))
        expect(self.page.get_by_role('heading', name='Local google identity provider')).to_be_visible()
        self.page.get_by_role('button', name='Continue as Alice', exact=True).click()
        self.assert_authenticated('google')
        expect(spinner).not_to_be_visible()
        self.page.goto(BASE_URL + '/settings/')
        self.page.get_by_label('Email (optional)', exact=True).fill('spinner@example.test')
        self.page.get_by_role('button', name='Save changes', exact=True).click()
        expect(spinner).to_be_visible()
        expect(self.page.get_by_text('Saved changes.', exact=True)).to_be_visible()
        expect(spinner).not_to_be_visible()
        self.page.get_by_test_id('account-avatar').click()
        self.page.get_by_role('menuitem', name='Log out', exact=True).click()
        expect(spinner).to_be_visible()
        expect(self.page).to_have_url(BASE_URL + '/')
        expect(self.page.get_by_role('button', name='Log in', exact=True)).to_be_visible()
        expect(spinner).not_to_be_visible()
        network.detach()

    def test_modal_keyboard_escape_and_focus_restoration(self):
        self.page.goto(BASE_URL + '/')
        button = self.page.get_by_role('button', name='Log in', exact=True)
        button.click()
        dialog = self.page.get_by_role('dialog')
        expect(dialog).to_be_visible()
        for provider in PROVIDERS:
            expect(dialog.get_by_role('link', name='Continue with ' + LABELS.get(provider, provider.capitalize()), exact=True)).to_be_visible()
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

    def test_avatar_menu_survives_viewport_changes_and_supports_click_and_right_click(self):
        self.login()
        avatar = self.page.get_by_test_id('account-avatar')
        expect(avatar).to_be_visible()
        colour = avatar.evaluate('element => getComputedStyle(element).backgroundColor')
        for width in [320, 360, 390, 640, 1024, 1440]:
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 800})
                expect(avatar).to_be_visible()
                bounds = avatar.bounding_box()
                self.assertGreaterEqual(bounds['x'], 0)
                self.assertLessEqual(bounds['x'] + bounds['width'], width)
                self.assertEqual(avatar.evaluate('element => getComputedStyle(element).backgroundColor'), colour)
                avatar.click()
                menu = self.page.get_by_role('menu')
                expect(menu).to_be_visible()
                item = self.page.get_by_role('menuitem', name='Log out', exact=True)
                expect(item).to_be_focused()
                bounds = menu.bounding_box()
                self.assertGreaterEqual(bounds['x'], 0)
                self.assertLessEqual(bounds['x'] + bounds['width'], width)
                if width == 320:
                    self.page.screenshot(path=str(ARTIFACTS / 'account-menu-mobile.png'), full_page=True)
                item.press('Escape')
                expect(menu).not_to_be_visible()
                expect(avatar).to_be_focused()
                avatar.click(button='right')
                expect(menu).to_be_visible()
                self.page.get_by_role('heading', level=1).click()
                expect(menu).not_to_be_visible()
                self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), width)

    def test_polish_account_menu_keyboard_logout_clears_the_real_session(self):
        self.login(route='/pl/')
        avatar = self.page.get_by_test_id('account-avatar')
        avatar.press('Shift+F10')
        item = self.page.get_by_role('menuitem', name='Wyloguj', exact=True)
        expect(item).to_be_focused()
        item.press('Escape')
        expect(avatar).to_be_focused()
        avatar.press('Enter')
        self.page.get_by_role('menuitem', name='Wyloguj', exact=True).press('Enter')
        expect(self.page.get_by_role('button', name='Zaloguj się', exact=True)).to_be_visible()
        expect(avatar).to_have_count(0)
        self.assertFalse(any(c['name'] == 'RSDS_ACCESS' for c in self.context.cookies()))
        self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/me').status, 401)

    def test_missing_access_cookie_recovers_same_account_avatar_with_real_refresh(self):
        self.login()
        original = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.context.clear_cookies(name='RSDS_ACCESS')
        self.page.set_viewport_size({'width': 320, 'height': 800})
        self.page.reload()
        expect(self.page.get_by_test_id('account-avatar')).to_be_visible()
        self.access_cookie()
        identity = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.assertEqual(identity['subject'], original['subject'])
        self.assertEqual(identity['avatarColor'], original['avatarColor'])

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

    def test_all_providers_sign_in_without_email_and_never_link_matching_addresses(self):
        subjects = set()
        for provider in PROVIDERS:
            self.context.clear_cookies()
            self.login(provider)
            self.assert_authenticated(provider)
            identity = self.context.request.get(BASE_URL + '/api/auth/me').json()
            self.assertEqual(identity['email'], '')
            self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/settings').json()['email'], '')
            subjects.add(identity['subject'])
            self.context.clear_cookies()
            self.login(provider)
            repeated = self.context.request.get(BASE_URL + '/api/auth/me').json()
            self.assertEqual(repeated['subject'], identity['subject'])
            self.assertEqual(repeated['avatarColor'], identity['avatarColor'])
        self.assertEqual(len(subjects), 5, 'Matching provider emails cannot link internal accounts')

    def test_unverified_email_signs_in_immediately_without_linking_verified_owner(self):
        self.login('google')
        owner = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.context.clear_cookies()
        self.login('google', 'Continue with unverified email')
        self.assert_authenticated('google')
        identity = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.assertEqual(identity['email'], '')
        self.assertNotEqual(identity['subject'], owner['subject'])
        self.context.clear_cookies()
        self.login('google', 'Continue with unverified email')
        self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/me').json()['subject'], identity['subject'])

    def test_missing_email_signs_in_and_optional_contact_is_saved_on_full_settings_page(self):
        self.login('github', 'Continue without email')
        expect(self.page.get_by_test_id('account-avatar')).to_be_visible()
        expect(self.page.get_by_role('dialog')).not_to_be_visible()
        original = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.assertEqual(original['email'], '')
        self.page.get_by_test_id('account-avatar').click()
        self.page.get_by_role('menuitem', name='Settings', exact=True).click()
        expect(self.page).to_have_url(BASE_URL + '/settings/')
        expect(self.page.get_by_role('heading', level=1, name='Settings')).to_be_visible()
        self.page.wait_for_function("document.querySelector('.brand-logo').naturalWidth > 0")
        email = self.page.get_by_label('Email (optional)', exact=True)
        expect(email).to_have_value('')
        self.assertFalse(email.get_attribute('required'))
        email.fill('alice@example.test')
        self.page.get_by_role('button', name='Save changes', exact=True).click()
        expect(self.page.get_by_role('status')).to_contain_text('Saved')
        self.page.reload()
        expect(email).to_have_value('alice@example.test')
        identity = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.assertEqual(identity['subject'], original['subject'])
        self.assertEqual(identity['email'], '')
        settings = self.context.request.get(BASE_URL + '/api/auth/settings').json()
        self.assertFalse(settings['emailVerified'])
        self.assertEqual(self.context.request.put(BASE_URL + '/api/auth/settings', data={'email': ''}).status, 403)
        email.fill('')
        self.page.get_by_role('button', name='Save changes', exact=True).click()
        expect(self.page.get_by_role('status')).to_contain_text('Saved')
        self.page.reload()
        expect(email).to_have_value('')
        self.context.clear_cookies()
        self.login('github', 'Continue without email')
        expect(self.page.get_by_test_id('account-avatar')).to_be_visible()
        self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/me').json()['subject'], original['subject'])

    def test_facebook_without_email_opens_polish_settings_without_onboarding(self):
        self.page.set_viewport_size({'width': 320, 'height': 800})
        self.login('facebook', 'Continue without email', route='/pl/')
        expect(self.page.get_by_test_id('account-avatar')).to_be_visible()
        expect(self.page.get_by_role('dialog')).not_to_be_visible()
        self.page.get_by_test_id('account-avatar').click()
        self.page.get_by_role('menuitem', name='Ustawienia', exact=True).click()
        expect(self.page).to_have_url(BASE_URL + '/pl/settings/')
        expect(self.page.get_by_role('heading', level=1, name='Ustawienia')).to_be_visible()
        self.page.wait_for_function("document.querySelector('.brand-logo').naturalWidth > 0")
        expect(self.page.get_by_label('Email (opcjonalny)', exact=True)).to_have_value('')
        self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'), 320)
        self.page.screenshot(path=str(ARTIFACTS / 'settings-mobile-pl.png'), full_page=True)

    def test_logout_from_settings_returns_to_localized_home_and_clears_session(self):
        for language, home, settings, logout in [('en', '/', '/settings/', 'Log out'), ('pl', '/pl/', '/pl/settings/', 'Wyloguj')]:
            with self.subTest(language=language):
                self.context.clear_cookies()
                self.login(route=home)
                self.page.goto(BASE_URL + settings)
                expect(self.page.get_by_label('Email (optional)' if language == 'en' else 'Email (opcjonalny)', exact=True)).to_be_visible()
                self.page.get_by_test_id('account-avatar').click()
                self.page.get_by_role('menuitem', name=logout, exact=True).click()
                expect(self.page).to_have_url(BASE_URL + home)
                expect(self.page.get_by_role('button', name='Log in' if language == 'en' else 'Zaloguj się', exact=True)).to_be_visible()
                expect(self.page.get_by_label('Email (optional)' if language == 'en' else 'Email (opcjonalny)', exact=True)).to_have_count(0)
                self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/me').status, 401)

    def test_settings_are_not_exposed_to_anonymous_visitors(self):
        self.page.goto(BASE_URL + '/settings/')
        expect(self.page.get_by_text('Sign in to open settings.', exact=True)).to_be_visible()
        expect(self.page.get_by_label('Email (optional)', exact=True)).to_have_count(0)
        self.assertEqual(self.context.request.get(BASE_URL + '/api/auth/settings').status, 401)

    def test_bound_provider_email_change_keeps_the_internal_account(self):
        self.login('google')
        original = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.context.clear_cookies()
        self.login('google', 'Continue as Alice with changed email')
        identity = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.assertEqual(identity['subject'], original['subject'])
        self.assertEqual(identity['email'], original['email'])

    def test_apple_private_relay_is_discarded_and_provider_account_is_distinct(self):
        self.login('google')
        original = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.context.clear_cookies()
        self.login('apple', 'Continue with Apple relay')
        identity = self.context.request.get(BASE_URL + '/api/auth/me').json()
        self.assertEqual(identity['email'], '')
        self.assertNotEqual(identity['subject'], original['subject'])



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
    summary = {'browser': 'chromium', 'headless': True, 'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'passed': result.wasSuccessful() and result.testsRun >= 25, 'providerBoundary': 'local-protocol-fixture'}
    (ARTIFACTS / 'auth-results.json').write_text(json.dumps(summary, indent=2))
    suite = ET.Element('testsuite', tests=str(result.testsRun), failures=str(len(result.failures)), errors=str(len(result.errors)))
    for test, detail in result.failures + result.errors:
        ET.SubElement(ET.SubElement(suite, 'testcase', name=test.id()), 'failure').text = detail
    ET.ElementTree(suite).write(ARTIFACTS / 'auth-junit.xml', encoding='utf-8', xml_declaration=True)
    raise SystemExit(0 if summary['passed'] else 1)
