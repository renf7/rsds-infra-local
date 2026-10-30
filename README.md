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

From PowerShell in this repository (the `.cmd` launcher does not require changing PowerShell execution policy). Select the context for the build too: `build.cmd` invokes Docker directly, before the runner can read `--docker-context`.

```powershell
$env:DOCKER_CONTEXT = 'desktop-linux'
docker --context desktop-linux info
.\build.cmd
if ($LASTEXITCODE -ne 0) { throw 'Build failed; do not run an older binary' }
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

To test two PRs together (these are the dependency-consolidation PRs validated on 30 October 2026; substitute the PR numbers you actually want to review):

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --pr rsds-infra-helm=8 --pr rsds-infra-company-page=16 --port 18081 --workdir .local-review
```

Full PR URLs also work:

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --pr https://github.com/renf7/rsds-infra-helm/pull/8 --pr https://github.com/renf7/rsds-infra-company-page/pull/16 --port 18081 --workdir .local-review
```

An unspecified repository always uses its default branch. Unknown repositories, duplicate overrides, foreign GitHub owners and invalid PR numbers are rejected. PR references select their **head commits**, not GitHub's synthetic merge commit.

## Linux / macOS

```sh
export DOCKER_CONTEXT=default
docker --context "$DOCKER_CONTEXT" info
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
6. Requests the configured English/Polish pages and assets through the Service. Source assets use checkout hashes; generated HTML is compared with files copied from the immutable image ID built from the selected Git commit. This supports static pages and compiled React output while retaining content/provenance checks.
7. Runs 16 **headless Chromium E2E tests only when `--e2e` is explicitly supplied**. Browser E2E is disabled by default; normal startup does not build/download the browser image. With E2E enabled, no browser window opens and no host Python/Node/browser installation is needed. First enabled run downloads the browser image; later builds reuse Docker layers.
8. Saves `report.json` (commits, PR/default branch, image IDs, HTTP checks, `e2eEnabled` and optional browser summary) and `pods.json`; enabled browser tests also produce `e2e/` artifacts. `PASS` means all checks requested for that run succeeded. The log/report explicitly identify when browser E2E was disabled.

## Optional headless E2E tests

Add `--e2e` to `up` to run the suite in [e2e/test_site.py](e2e/test_site.py):

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --e2e
.\out\rsds-local.exe up --docker-context desktop-linux --pr rsds-infra-helm=8 --pr rsds-infra-company-page=16 --e2e --port 18081 --workdir .local-review
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

## Reproduce the successful local run

This is the procedure used on Windows with PowerShell and Docker Desktop's Linux engine, verified on 30 October 2026. It does not depend on the original user's directory, preinstalled Go/Python/Node, GitHub login or Sonar credentials. Start from the public clone above and run commands from its root. The same workflow on Linux/macOS uses `sh build.sh`, `./out/rsds-local`, and the verified local context name instead of the Windows executable/context.

1. Start Docker Desktop and wait until the Linux engine is ready. On this machine it was initially stopped; starting the application was necessary before any build or test. Docker Desktop can be opened from the Start menu, or from its usual Windows installation path:

   ```powershell
   Start-Process -FilePath "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe" -WindowStyle Hidden
   docker context ls
   docker --context desktop-linux info --format '{{.ServerVersion}} {{.OSType}}'
   Get-Command git, docker, kubectl
   ```

   Wait for `docker info` to succeed and show `linux` before continuing. If installed elsewhere, open Docker Desktop normally. Enable Linux containers through Docker Desktop if necessary. The tested server version was 29.5.2; this is evidence, not a requirement to install that exact version. Docker Desktop's own installation/virtualization prerequisites must already work.

2. Build the current checkout, selecting the same Docker context for the build container:

   ```powershell
   $env:DOCKER_CONTEXT = 'desktop-linux'
   .\build.cmd
   if ($LASTEXITCODE -ne 0) { throw 'Build failed; do not run an older binary' }
   .\out\rsds-local.exe up --help
   ```

   The build uses `golang:1.26-alpine` in Docker and writes `out/rsds-local.exe`. No host Go installation was added. The binary must be rebuilt after switching branches or pulling runner changes; an old executable can otherwise reject a newer manifest or run old behavior. Setting `DOCKER_CONTEXT` here affects this terminal and its child processes; no global `docker context use` is needed.

3. Choose a free port, a new workdir and a unique cluster name. Existing previews occupied other ports on this machine, so this run used 18087. Do not stop somebody else's containers to free a port.

   ```powershell
   Get-NetTCPConnection -State Listen -LocalPort 18087 -ErrorAction SilentlyContinue
   .\out\rsds-local.exe up --docker-context desktop-linux --pr rsds-infra-company-page=16 --pr rsds-infra-helm=8 --e2e --port 18087 --cluster rsds-local-dependency-review --workdir .local-dependency-review
   if ($LASTEXITCODE -ne 0) { throw 'Local validation failed; inspect the retained run' }
   ```

   No `--pr` means **all actual default branches**; it does not mean the current working copies of neighboring repositories. To validate those defaults separately, choose a different workdir, port and cluster:

   ```powershell
   .\out\rsds-local.exe up --docker-context desktop-linux --e2e --port 18088 --cluster rsds-local-default-review --workdir .local-default-review
   ```

   Omit `--e2e` for ordinary startup. Each enabled run executes browser tests during `up`; there is no separate `test` subcommand. To rerun against fresh commits, run `down` for that workdir and invoke `up` again. The runner fetches current PR heads, so inspect the recorded commits rather than assuming a PR number always means identical code.

4. Check the result, not just whether a page opens:

   ```powershell
   .\out\rsds-local.exe status --workdir .local-dependency-review
   $runRoot = '.local-dependency-review/runs/rsds-local-dependency-review'
   $runReport = Get-Content "$runRoot/report.json" -Raw | ConvertFrom-Json
   $runReport | Select-Object status, url, e2eEnabled, e2e
   $runReport.sources | ConvertTo-Json -Depth 4
   $runReport.results | Format-Table path, status, sourceMatches
   Get-Content "$runRoot/e2e/results.json"
   ```

   `status` displays recorded state and queries current pods/services; it does not rerun HTTP checks or E2E. For the enabled suite, require a zero exit code, `status=PASS`, `e2eEnabled=true`, and `e2e.passed=true` with 16 tests, zero failures and zero errors. Every HTTP result must have `status=200` and `sourceMatches=true`. Use the report's `url` to inspect `/` and `/pl/` manually. `PASS` with `e2eEnabled=false` is an HTTP/deployment pass only.

5. Preserve the artifacts you need, then stop only this run:

   ```powershell
   .\out\rsds-local.exe down --workdir .local-dependency-review
   # Only if you also started the separate default-branch example:
   .\out\rsds-local.exe down --workdir .local-default-review
   ```

   Always pass the same `--workdir` to `status` and `down` that you used for `up`. `down` retains reports/checkouts and cached images; it does not reclaim every downloaded image. Do not delete `state.json` to bypass the ownership checks, use `docker system prune`, or remove another preview's cluster.

### What was changed or handled on the original machine

| Observed challenge | Resolution used / how to reproduce |
| --- | --- |
| Docker Desktop was not running | Started Docker Desktop and waited for `docker info` on `desktop-linux`; application startup is a prerequisite, not a runner side effect. |
| Newer kind default node failed on Docker Desktop using cgroup v1 | Pinned the runner's node image to `kindest/node:v1.34.0`. The failed newer default was Kubernetes 1.37. No Docker/cgroup settings were changed. Keep the repository's node pin; do not substitute kind's default during troubleshooting. |
| kind/Helm were not on the user's PATH | Runner downloaded kind 0.33.0 and Helm 4.3.1 into the selected workdir's `bin/`, checking upstream SHA-256 checksums. No global install or PATH edit was required. Existing PATH tools take precedence; check their versions if your behavior differs. |
| PowerShell script policy could obstruct a `.ps1` launcher | Used `build.cmd` from PowerShell; no execution-policy change. |
| Other local previews already used ports/clusters | Used a separate workdir, loopback port and `rsds-local-*` cluster. Existing previews were left running. |
| Git reported dubious repository ownership in agent-managed checkouts | Runner uses a per-command `git -c safe.directory=<exact-managed-checkout>` for its own clones. No global wildcard trust was configured. For manual Git operations, use a normal user-owned clone, or scope `-c safe.directory=...` to that one trusted absolute path. |
| Browser tooling was absent on the host | Built the repository's E2E Docker image only with explicit `--e2e`. Playwright Python and its image are version-matched; no host browser/Python installation was needed. |
| Generated HTML is not identical to a source template | Runner supports `imageFile` checks: copy expected HTML from the immutable built image ID and compare served bytes. Unchanged CSS/branding assets still use source-file hashes. Rebuild the runner when this manifest support changes. |
| Agent sandbox restricted Docker/network operations | Docker engine access and public downloads were run with the environment's authorized tool permissions. This is an agent-host restriction, not a requirement for Windows Administrator mode. If an agent cannot reach Docker, it must report the restriction and use its host's approval mechanism; never weaken Docker isolation or claim unexecuted tests passed. |

The runner creates a private kubeconfig, loads the locally built image into kind, installs the real chart with local-only ingress/NodePort/image overrides, and creates temporary containers to read built files and run Chromium. It removes those temporary containers after use. No Kubernetes context switch, production credentials, cloud access, registry push, host package installation, Docker resource-setting change or global Git configuration was needed. Initial manual Helm experiments were superseded by this runner; users do not need to repeat them. A fresh anonymous clone was also exercised with automatic tool provisioning, ordinary startup without E2E, and explicit E2E startup.

For the dependency review, the recorded frontend commit was `488db335ce769509a5d9ae0e8dcba44088a11969` and Helm commit was `579707dd078fc637bc573d7a567710e9869d7d2d`: five HTTP/content checks and all 16 headless Chromium tests passed. See [RSDSINFRA-27](https://rsdsoftware.atlassian.net/browse/RSDSINFRA-27), [frontend PR #16](https://github.com/renf7/rsds-infra-company-page/pull/16), and [Helm PR #8](https://github.com/renf7/rsds-infra-helm/pull/8). These historical SHAs are evidence, not a promise about later PR revisions.

### Troubleshooting without losing evidence

| Symptom | Next action |
| --- | --- |
| Docker named-pipe/socket error, engine unreachable or Windows container error | Start Docker Desktop, select Linux containers, inspect `docker context ls` and retry `docker --context <local-context> info`. Use the same verified context in the build environment and `up`. Do not point the runner at a remote TCP/SSH engine. |
| `git`, `docker` or `kubectl` not found | Install/repair the named prerequisite and open a new terminal so PATH is refreshed. The runner provisions kind/Helm only, not Docker/Git/kubectl. |
| Port in use, active state, or cluster already exists | Inspect `status --workdir ...`. Stop only that owned run, or choose another workdir/port/cluster. Never overwrite state or delete unrelated containers. |
| kind/bootstrap or Helm readiness timeout | Preserve `report.json` and the command error. Use the diagnostics below with the run's private kubeconfig/context. Confirm the pinned node version and available Docker memory/disk; no resource minimum was measured. Concurrent clusters consume additional resources. Do not change production configuration or blindly enlarge limits. |
| Download/pull/build fails | First run needs internet and disk for Go, Kubernetes, nginx and optionally Chromium images, plus public GitHub/tool downloads. Check the original error, proxy/firewall/DNS and Docker disk space. Configure organization-approved proxy/CA settings where required; do not bypass TLS or checksum verification. Caches speed later runs but are not prerequisites. |
| Manifest reports unknown `imageFile` field | You have a stale executable. Rebuild from the same checkout as `local-test.json`; do not remove integrity checks. |
| HTTP/source mismatch or `FAILED_E2E` | Inspect the selected commits, `results`, browser logs, JUnit and traces. Fix the source/chart/test regression; do not bypass a failed test or label the run successful. |
| Sharing artifacts with another person/agent | Share selected report/test files after review, not the whole workdir. `state.json`, kubeconfig and raw pod output can contain credentials, paths or future service data. Reports also contain machine paths; sanitize those when necessary. |

Diagnostics for the explicit cluster/workdir example above (substitute the report's actual paths and cluster for other runs):

```powershell
$runRoot = '.local-dependency-review/runs/rsds-local-dependency-review'
docker --context desktop-linux logs rsds-local-dependency-review-control-plane
kubectl --kubeconfig "$runRoot/kubeconfig" --context kind-rsds-local-dependency-review get nodes
kubectl --kubeconfig "$runRoot/kubeconfig" --context kind-rsds-local-dependency-review -n rsds-local-test get pods,svc
kubectl --kubeconfig "$runRoot/kubeconfig" --context kind-rsds-local-dependency-review -n rsds-local-test get events --sort-by=.lastTimestamp
kubectl --kubeconfig "$runRoot/kubeconfig" --context kind-rsds-local-dependency-review -n rsds-local-test logs -l app.kubernetes.io/instance=rsds-local --all-containers=true --tail=100
```

### Instructions for AI agents

Read this README, [AGENTS.md](AGENTS.md) and the repository security standard before making changes. Verify Docker readiness and local context, preserve existing runs, build the current checkout, choose isolated state/ports, and pass `--e2e` only when tests were requested. Record runner revision, selected source SHAs, image IDs, invocation, exit status and actual test counts. Report missing credentials/network/Docker access as a limitation, not a passing result. Never use the global Kubernetes context, expose private kubeconfigs, deploy production, or weaken scanner/tests to obtain PASS. Keep this runbook synchronized when commands, prerequisites, pins or known compatibility issues change.

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
