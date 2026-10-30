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

Country responses are mocked; tests never call the external country service. The HTTP 503 scenario accepts only the deliberately mocked endpoint's exact 503 response/resource message. Other HTTP, console, request or JavaScript errors still fail. Contact links are inspected without launching an email client or sending email.

These tests cover current static behavior. They do not claim pixel-perfect visual regression or coverage of future login, theme switching, backend services or role authorization. Keep the behavioral contracts when the frontend implementation changes, adjusting selectors only where necessary.
