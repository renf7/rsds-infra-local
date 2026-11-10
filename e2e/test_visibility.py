"""Opt-in runtime ConfigMap E2E; invoked by scripts/Test-ProviderVisibility.ps1.

Only the external identity provider is a fixture. Browser/JWT/API/DB are real.
The host changes Kubernetes config via a file handshake; no kubeconfig/token is
mounted into the browser container and no application responses are mocked.
"""
import json
import os
from pathlib import Path
import time
from playwright.sync_api import expect, sync_playwright

base = os.environ['BASE_URL']
control = Path('/control')
stages = [('google', ['google']), ('', []), ('unknown', []),
          ('facebook,microsoft,google,github', ['facebook', 'microsoft', 'google', 'github'])]

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    member = browser.new_context()
    member.route('https://api.country.is/**', lambda route: route.fulfill(json={'country': 'US'}))
    page = member.new_page()
    page.goto(base + '/')
    page.get_by_role('button', name='Log in', exact=True).click()
    page.get_by_role('link', name='Continue with Google', exact=True).click()
    page.get_by_role('button', name='Continue as Alice', exact=True).click()
    expect(page.get_by_test_id('account-avatar')).to_be_visible()
    identity = member.request.get(base + '/api/auth/session').json()['subject']
    guests = []
    for language, width in [('en', 320), ('en', 1440), ('pl', 320), ('pl', 1440)]:
        context = browser.new_context(viewport={'width': width, 'height': 900})
        context.route('https://api.country.is/**', lambda route: route.fulfill(json={'country': 'US'}))
        guest = context.new_page()
        guest.goto(base + ('/pl/' if language == 'pl' else '/'))
        guest.get_by_role('button', name='Zaloguj się' if language == 'pl' else 'Log in', exact=True).click()
        expect(guest.get_by_role('dialog').get_by_role('link')).to_have_count(4)
        guests.append(guest)
    for index, (value, expected) in enumerate(stages):
        temporary = control / 'request.tmp'
        temporary.write_text(json.dumps({'index': index, 'value': value}), encoding='utf-8')
        temporary.replace(control / 'request.json')
        deadline = time.monotonic() + 180
        while not (control / f'applied-{index}').exists():
            assert time.monotonic() < deadline, 'Host did not apply ConfigMap'
            time.sleep(0.2)
        while True:
            response = member.request.get(base + '/api/auth/providers')
            assert 'no-store' in response.headers.get('cache-control', '')
            visible = [item['id'] for item in response.json() if item.get('visible')]
            if visible == expected:
                break
            assert time.monotonic() < deadline, 'ConfigMap visibility did not propagate'
            time.sleep(1)
        for guest in guests:
            links = guest.get_by_role('dialog').get_by_role('link')
            expect(links).to_have_count(len(expected), timeout=12000)
            assert [link.get_attribute('href').split('/')[-1].split('?')[0]
                    for link in links.all()] == expected
            if not expected:
                expect(guest.get_by_role('dialog').get_by_role('status')).to_be_visible()
            assert guest.locator('a[href*="authorization/apple"]').count() == 0
        session = member.request.get(base + '/api/auth/session').json()
        assert session['authenticated'] and session['subject'] == identity
        print(f'PASS runtime stage {index}: {expected}; existing JWT session preserved', flush=True)
        (control / f'done-{index}').write_text('ok', encoding='utf-8')
    browser.close()
    (control / 'result.json').write_text(json.dumps({
        'passed': True, 'stages': len(stages), 'headless': True,
        'identityProviderMode': 'local-protocol-fixture'}), encoding='utf-8')
