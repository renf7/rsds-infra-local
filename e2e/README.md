# Static site behavior coverage

Run with `rsds-local up --docker-context <local-context> --e2e`. Browser E2E remains **disabled by default**. CI explicitly enables it for default-branch and selected-PR deployments. The suite exercises the actual deployed HTML/CSS/JavaScript, not a duplicate implementation.

| Existing behavior | Browser assertions |
| --- | --- |
| English and Polish pages | Correct document language/current-language marker, branding image loaded, title, headings/sections, contact address and healthy resources |
| Section navigation | All five desktop navigation links and both hero CTAs navigate to their real section; heading reaches the viewport |
| Brand/home link | Returns to the current language's home page and shows the hero |
| Keyboard use | English/Polish language links accept focus and activate with Enter |
| Responsive navigation | At 320, 390 and 640px regular nav links are hidden; at 641 and 1024px they are visible; contact/language controls remain visible without horizontal overflow |
| Manual language selection | Changes route, persists choice and survives navigation/reload |
| Preference precedence | Saved English wins over Polish country detection; saved Polish redirects `/index.html` preserving query/fragment; both avoid country API requests |
| Country caching | Cached Polish redirects without lookup; lowercase US response normalizes to US and prevents repeat lookups across entry navigation/reload |
| Explicit Polish URL | Remains directly accessible despite a saved English preference, without overwriting that preference or calling the country API |
| Storage unavailable | Denied local/session storage does not break page rendering or manual language navigation |
| Country lookup unavailable | Missing country or a mocked HTTP 503 leaves English usable and contact navigation working |
| Mobile use | English/Polish pages, language selection and contact CTA work at a phone viewport |

There are 16 test methods, with both language routes and multiple viewport widths exercised within relevant scenarios. The runner requires at least 16 successful headless tests and fails on incomplete reports. JSON/JUnit, screenshots, traces and browser logs are retained per managed run.

Sequential section/CTA checks wait for native smooth scrolling to settle before the next click, then recheck the destination heading. An element can enter the viewport while scrolling is still in progress; clicking the next anchor during that animation caused a local navigation timing failure. The test keeps the real animation, URL checks and viewport assertions; it does not force-scroll elements, disable animation, retry failures or increase assertion timeouts.

Country responses are mocked; tests never call the external country service. The HTTP 503 scenario accepts only the deliberately mocked endpoint's exact 503 response/resource message. Other HTTP, console, request or JavaScript errors still fail. Contact links are inspected without launching an email client or sending email.

These tests cover current static behavior. They do not claim pixel-perfect visual regression or coverage of future login, theme switching, backend services or role authorization. Keep the behavioral contracts when the frontend implementation changes, adjusting selectors only where necessary.

## Optional authentication integration

Select `--manifest local-test-auth.json --e2e` and the four matching PR overrides documented in the root README. This runs 46 headless tests: the 16 existing marketing behavior tests plus 30 authentication tests. Authentication remains disabled in the default manifest; browser tests always require the explicit flag.

All five provider flows traverse the real browser, Spring Security callback, real DynamoDB Local adapter, signed JWT cookie and authenticated API. The local provider fixture replaces only external OAuth/OIDC endpoints. It checks state-bound one-use authorization codes, redirects, nonce, supported PKCE and Apple's real ES256 client-secret signature using a public key only. Tests cover consent denial, invalid OIDC signatures, forged state, tampered JWTs, CSRF, logout, refresh replay, Polish return navigation and the signed-in 320px header.

Reports explicitly identify `identityProviderMode=local-protocol-fixture`. No live provider accounts or app registrations are used, so this is not proof of live-provider interoperability, consent policies or MFA. Authentication traces are omitted to avoid recording credentials; screenshots, JSON and JUnit remain. Never upload generated signing keys, kubeconfigs, JWTs or cookies.

Account onboarding includes five scenarios within the 46-test suite (30 auth), using actual local SMTP capture. Microsoft/Facebook's first binding and any missing/unverified email require a code. GitHub's fixture intentionally hides public email and requires authenticated /emails with user:email scope. The same verified email across providers must yield the same internal subject. An upstream changed email cannot move an existing provider binding; an Apple relay address stays a distinct email key. Code values are never included in reports/screenshots/traces.

The avatar menu is tested at 320, 360, 390, 640, 1024 and 1440px with click/right-click, keyboard activation and Escape focus restoration. Polish menu logout clears the real session. Removing only the access cookie must recover the same account/avatar through the real CSRF-protected refresh endpoint. These tests use provider-boundary fixtures only, never manual OAuth credentials.

Missing provider email now signs in immediately using the stable provider identity. Full-page /settings/ and /pl/settings/ coverage checks optional contact-email save/clear/reload, no account linking, CSRF, anonymous denial and Polish mobile layout. Unverified provider-supplied email retains ownership verification; absent email does not trigger onboarding.
