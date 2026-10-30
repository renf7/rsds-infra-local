# rsds-infra-local

Run the RSDS-INFRA application locally through its real Helm chart before production deployment. Jira: [RSDSINFRA-25](https://rsdsoftware.atlassian.net/browse/RSDSINFRA-25).

## Prerequisites

- Docker Desktop with Linux containers (or a local Linux Docker engine), running.
- Git and kubectl on PATH. Docker Desktop includes kubectl on Windows.
- Internet access for public source, images, and checksum-verified tool downloads.
- Local Docker context: run `docker context ls` and select the local context explicitly.

No Python, Node, Go, global Kubernetes configuration, AWS credentials, production access or registry push credentials are needed to use the binary. Build it with a temporary Go Docker container. kind 0.33.0 and Helm 4.3.1 are downloaded into the managed workdir when absent from PATH. Kubernetes is pinned to 1.34.0 because the newer default kind image failed to bootstrap on the tested Docker Desktop cgroup-v1 environment. No Docker Desktop settings are changed.

## Windows: build and start

From a terminal in this repository (the `.cmd` launcher does not require changing PowerShell execution policy):

```powershell
.\build.cmd
.\out\rsds-local.exe up --docker-context desktop-linux
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

On Docker Desktop for macOS the local context may be `desktop-linux`; inspect it first. Only local Unix-socket/named-pipe Docker endpoints are accepted; remote TCP/SSH Docker contexts are rejected.

## What `up` does

1. Reads `local-test.json`, checks arguments and confirms a free loopback port.
2. Makes fresh managed clones, selects PR heads or actual default branches, records full commit SHAs, builds all configured images, and records image IDs.
3. Creates a uniquely named `rsds-local-*` kind cluster with a private kubeconfig under `.local/runs/`. It never selects your global production Kubernetes context.
4. Loads the images directly into kind, installs the selected chart with AWS ingress disabled and image pulling disabled, and waits for readiness.
5. Applies a **local-only** NodePort override and exposes it on `127.0.0.1` at the requested port. This override is not committed to the application chart.
6. Requests the configured English/Polish pages and assets through the Service and verifies that response bytes match the selected source checkout. Saves `report.json` (commits, PR/default branch, image IDs, checks) and `pods.json`.

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
