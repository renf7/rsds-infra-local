# Scanner coverage and version audit

Verified 30 October 2026 against official upstream GitHub releases and the repository's security settings. All configured tools/features are free for this public repository. Action references are pinned to reviewed commit SHAs.

| Check | Version / scope | Trigger |
| --- | --- | --- |
| CodeQL | Action 4.39.1; Go, Python E2E tooling and GitHub Actions; security-extended queries | Every PR update, main pushes, weekly |
| Semgrep Community Edition | 1.183.0; OSS engine, community p/default rules; no account | Every PR update, main pushes, weekly |
| Trivy repository | CLI 0.76.1 / Action 0.36.0; dependencies, misconfiguration, secrets | Every PR update, main pushes, weekly |
| PR dependency vulnerability scan | Trivy 0.76.1; full manifest scan, not native base/head dependency diff | Every PR update |
| SonarQube Cloud | Scan Action 8.4.0; public rsds-infra-local project, blocking quality gate | Same-repository PRs to main, main pushes, weekly |
| Go checks | gofmt, go test -race, go vet; Go 1.26 | Every PR update and main pushes |
| Trivy E2E image | CLI 0.76.1 / Action 0.36.0; built browser test image vulnerabilities/secrets | Every PR update, main pushes, weekly |
| Dependabot version updates | GitHub Actions, pip scanner/E2E tools, Go modules, E2E Docker base | Weekly after configuration reaches main |
| Dependabot alerts / security fixes | Native free features; enabled and read back via API | GitHub advisory/dependency processing |
| Secret scanning / push protection | Native free public-repository features; verified enabled via API | GitHub scanning and supported-secret push blocking |

PR workflows explicitly handle opened, synchronize, reopened, edited and ready_for_review. Synchronize covers each new commit and force-push; no source-path filters are used. Superseded runs are cancelled. Sonar's token is never supplied to fork PRs. Native Dependabot and secret protection are event-driven services rather than per-commit CI jobs; Trivy additionally scans dependencies and secrets on PR updates.

No React/Java tooling is installed: this repository is permanently scoped to Go and local-test orchestration. Playwright Python 1.64.1 matches official mcr.microsoft.com/playwright/python:v1.64.1-noble (verified from PyPI and registry on 30 October 2026). The derived image applies OS updates and removes unused Firefox/WebKit, GStreamer and Python build tools after Trivy findings; the suite uses Chromium only. Python is browser-test tooling only. Application containers built for local tests belong to their source repositories; their publishing pipelines retain responsibility for container scanning before publication. This repository builds/scans its browser test image locally and does not publish it.

Native status verified: secret_scanning enabled, secret_scanning_push_protection enabled, vulnerability-alerts GET returned HTTP 204, automated-security-fixes GET returned enabled=true and paused=false. No paid security tier was enabled. Branch protection is not asserted by this audit.

Upstream references:

- https://github.com/aquasecurity/trivy/releases/tag/v0.76.1
- https://github.com/aquasecurity/trivy-action/releases/tag/v0.36.0
- https://github.com/semgrep/semgrep/releases/tag/v1.183.0
- https://github.com/github/codeql-action/releases/tag/v4.39.1
- https://github.com/SonarSource/sonarqube-scan-action/releases/tag/v8.4.0

CodeQL bundle tags are separate from Action releases; do not replace an Action pin with a codeql-bundle tag. Dependabot proposes version changes; review upstream release notes and compatibility before updating pins. Keep the Sonar coverage threshold and security gates intact.

Authentication integration adds a second built-image scan for test-idp and pip/Docker Dependabot coverage. Its Python runtime is updated to 3.15.2 (latest stable verified at https://www.python.org/downloads/ on 30 October 2026), with cryptography 50.0.2. Runtime packaging tools are removed after installation: Trivy identified vulnerable vendored msgpack/urllib3 in unused pip/ensurepip. Neither the image nor findings are excluded from scanning. The local provider fixture receives public Apple client trust only.
