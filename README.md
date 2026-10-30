# rsds-infra-local

Run the RSDS-INFRA application locally through its real Helm chart before production deployment. Jira: [RSDSINFRA-25](https://rsdsoftware.atlassian.net/browse/RSDSINFRA-25).

## Prerequisites

- Docker Desktop with Linux containers (or a local Linux Docker engine), running.
- Git and kubectl on PATH. Docker Desktop includes kubectl on Windows.
- Internet access for public source, images, and checksum-verified tool downloads.
- Local Docker context: run `docker context ls` and select the local context explicitly.

No Python, Node, Go, global Kubernetes configuration, AWS credentials, production access or registry push credentials are needed to use the binary. Build it with a temporary Go Docker container. kind 0.33.0 and Helm 4.3.1 are downloaded into the managed workdir when absent from PATH. Kubernetes is pinned to 1.34.0 because the newer default kind image failed to bootstrap on the tested Docker Desktop cgroup-v1 environment. No Docker Desktop settings are changed.

## Get the source

This is a public repository: users do not need GitHub credentials or a Sonar token to build/run it or execute browser tests. The implementation is currently under review in [PR #1](https://github.com/renf7/rsds-infra-local/pull/1). Until it is merged, clone its implementation branch:

```sh
git clone --branch RSDSINFRA-25-local-testing --single-branch https://github.com/renf7/rsds-infra-local.git
cd rsds-infra-local
```

After merge, a normal clone of the default branch will contain the tool. Start Docker Desktop in Linux-container mode before building; `docker info` must succeed. Git and kubectl must also be available in this terminal. The commands below run as a normal local user with permission to access Docker; an administrator terminal is not a product requirement. Windows Docker Desktop normally supplies docker and kubectl on PATH. Linux/macOS users must install kubectl separately if absent.

## Windows: build and start

From a terminal in this repository (the `.cmd` launcher does not require changing PowerShell execution policy):

```powershell
.\build.cmd
.\out\rsds-local.exe up --docker-context desktop-linux
```

To include the optional headless tests on startup, add `--e2e`:

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --e2e
```

Choose one startup command per workdir. If it is already running, use `status` to inspect it, then `down` before starting again with different options. By default the page is available at `http://127.0.0.1:18080`; choose `--port 18081` if that port is occupied. With E2E disabled, no browser image is downloaded or launched. Enabled runs save all 16 test results/screenshots/traces under the managed run directory.

```powershell
.\out\rsds-local.exe status
.\out\rsds-local.exe down
```

With **no `--pr`**, the chart and every configured image source are cloned from their repository's actual default branch, normally `main`. Images are built locally and tagged with the exact source commit. The runner does not pull a floating production `latest` image and pretend it represents a particular commit.

To test the current chart/frontend PRs together:

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --pr rsds-infra-helm=4 --pr rsds-infra-company-page=9 --port 18081
```

Full PR URLs also work:

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --pr https://github.com/renf7/rsds-infra-helm/pull/4 --pr https://github.com/renf7/rsds-infra-company-page/pull/9
```

An unspecified repository always uses its default branch. Unknown repositories, duplicate overrides, foreign GitHub owners and invalid PR numbers are rejected. PR references select their **head commits**, not GitHub's synthetic merge commit.

## Linux / macOS

```sh
sh build.sh
./out/rsds-local up --docker-context default
```

Use `./out/rsds-local up --docker-context default --e2e` to include browser tests. Stop the current workdir first with `./out/rsds-local down` if already running.

On Docker Desktop for macOS the local context may be `desktop-linux`; inspect it first. Only local Unix-socket/named-pipe Docker endpoints are accepted; remote TCP/SSH Docker contexts are rejected.

## What `up` does

1. Reads `local-test.json`, checks arguments and confirms a free loopback port.
2. Makes fresh managed clones, selects PR heads or actual default branches, records full commit SHAs, builds all configured images, and records image IDs.
3. Creates a uniquely named `rsds-local-*` kind cluster with a private kubeconfig under `.local/runs/`. It never selects your global production Kubernetes context.
4. Loads the images directly into kind, installs the selected chart with AWS ingress disabled and image pulling disabled, and waits for readiness.
5. Applies a **local-only** NodePort override and exposes it on `127.0.0.1` at the requested port. This override is not committed to the application chart.
6. Requests the configured English/Polish pages and assets through the Service and verifies that response bytes match the selected source checkout.
7. Runs 16 **headless Chromium E2E tests only when `--e2e` is explicitly supplied**. Browser E2E is disabled by default; normal startup does not build/download the browser image. With E2E enabled, no browser window opens and no host Python/Node/browser installation is needed. First enabled run downloads the browser image; later builds reuse Docker layers.
8. Saves `report.json` (commits, PR/default branch, image IDs, HTTP checks, `e2eEnabled` and optional browser summary) and `pods.json`; enabled browser tests also produce `e2e/` artifacts. `PASS` means all checks requested for that run succeeded. The log/report explicitly identify when browser E2E was disabled.

## Optional headless E2E tests

Add `--e2e` to `up` to run the suite in [e2e/test_site.py](e2e/test_site.py):

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --e2e
.\out\rsds-local.exe up --docker-context desktop-linux --pr rsds-infra-helm=4 --pr rsds-infra-company-page=9 --e2e
```

Without `--e2e` (or with `--e2e=false`), only the deployment and HTTP/source-integrity checks run. The enabled suite contains 16 scenarios covering the existing static site, including all section/CTA/home links, keyboard language selection, responsive breakpoints, language/country precedence and caching, blocked storage, and failed country lookups. See the [behavior coverage matrix](e2e/README.md). It also checks page sections, loaded branding, contact link, horizontal overflow, browser exceptions, console errors and failed resources. The country service is mocked for deterministic tests; unexpected external requests fail. Email links are checked without sending email. These tests do not claim SSO/backend coverage or pixel-perfect visual regression.

The browser container runs as an unprivileged user with capabilities dropped, no Docker socket, no host mounts and no production credentials. It joins the local kind network to reach the selected cluster's NodePort. Reports are copied out and the test container removed. A test/report/container failure makes `up` exit nonzero and records `FAILED_E2E`; the deployment is retained for inspection and normal `down` cleanup.

For enabled runs, the `e2e/` directory contains `results.json`, JUnit `junit.xml`, `browser.log`, screenshots and Playwright trace ZIPs. Open traces with a trusted local Playwright trace viewer when needed. Traces/screenshots can contain tested page content, so review them before sharing if future tests introduce private data. CI explicitly passes `--e2e` for both source-selection modes and uploads only these artifacts and the existing sanitized reports, never kubeconfig files. Jira: [RSDSINFRA-26](https://rsdsoftware.atlassian.net/browse/RSDSINFRA-26).

The chart and application security settings are inherited from the selected source revision. Testing `main` does not silently apply security settings that only exist in a PR. This is a functional local smoke test, not proof of production ingress/TLS, AWS ALB, SSO or future backend behavior.

**PR code and Dockerfiles execute locally. Only test revisions you trust.** No host credentials are mounted into application containers. A kind node is a privileged local container; the runner does not grant it access to your cloud account.

## Inspect and clean up

```powershell
.\out\rsds-local.exe status
.\out\rsds-local.exe down
```

`up` leaves the environment running for manual review. `down` deletes only the cluster recorded in this runner's owned state; it rejects production/unmanaged names and preserves reports and source checkouts. Docker image caches are retained. It does not prune Docker or remove unrelated containers. If startup fails, state is kept so `down` can remove a partially created cluster.

An existing active state is never overwritten: use `down` first or a separate `--workdir`. Multiple independent runs can use different workdirs and ports:

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --workdir .local-review --port 18081
.\out\rsds-local.exe down --workdir .local-review
```

Do not commit `.local*` directories: they include kubeconfig credentials and machine-specific state. The new repository's `.gitignore` excludes them.

## Add backend images later

`local-test.json` is the explicit image allowlist. Add one entry per existing backend, specifying its repository, Docker build context and actual Helm values prefix, for example `services.auth.image`. The chart must already deploy that service and understand those values. The runner then builds the backend from main/default unless its own `--pr rsds-infra-auth-service=NUMBER` override is supplied. Add meaningful API health checks when those services exist; the current manifest includes only the existing frontend. No placeholder backend is reported as tested.

## Development and free scanners

```sh
go test ./...
go vet ./...
go build ./cmd/rsds-local
```

The Go implementation uses only the standard library. Follow [AGENTS.md](AGENTS.md), the [scanner coverage/version audit](SCANNER-VERSIONS.md), and the central RSDS-INFRA scanner standard. Applicable scanners run on PR opened/synchronize/reopened/edited/ready-for-review events: CodeQL (Go/Actions), Semgrep CE, Trivy, dependency scanning and SonarCloud. Dependabot checks Actions, Go modules and the Semgrep pin weekly once its configuration reaches main. React lint and Java bytecode scanners are excluded from this Go/tooling-only repository.

SonarCloud needs a repository Actions secret `SONAR_TOKEN`, a public project key `rsds-infra-local` in organization `renf7`, verified free/OSS plan eligibility, and CI-based analysis. No enable flag is used; missing credentials fail visibly. Token-based scans exclude fork PRs. Main/PR results and coverage are separate; no quality gate is bypassed. Native secret scanning, push protection, Dependabot alerts and automated security fixes were enabled and verified on 30 October 2026; see [SECURITY.md](SECURITY.md). Required-check branch protection is a separate setting.
