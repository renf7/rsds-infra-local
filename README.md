# rsds-infra-local

Run RSDS-INFRA Helm deployments locally, from actual default branches or selected pull requests, with optional headless browser tests.

The implementation is under review in [PR #1](https://github.com/renf7/rsds-infra-local/pull/1). Until it is merged, use its public implementation branch:

```sh
git clone --branch RSDSINFRA-25-local-testing --single-branch https://github.com/renf7/rsds-infra-local.git
cd rsds-infra-local
```

Prerequisites: running Docker with Linux containers, Git and kubectl on PATH, internet access, and permission to use your local Docker engine. Helm and kind download automatically when absent. No GitHub login, Sonar token, Go/Python/Node or host browser installation is needed for local use.

On Windows with Docker Desktop:

```powershell
.\build.cmd
.\out\rsds-local.exe up --docker-context desktop-linux
```

Browser E2E is disabled by default. To include all 16 headless static-site tests, add `--e2e` to startup:

```powershell
.\out\rsds-local.exe up --docker-context desktop-linux --e2e
```

Choose one startup command per workdir. If already running, stop it with `.\out\rsds-local.exe down` before restarting with different options. The default URL is http://127.0.0.1:18080; use `--port 18081` if occupied.

For Linux/macOS, build with `sh build.sh`, then use `./out/rsds-local up --docker-context default` (optionally `--e2e`). Select your actual local context from `docker context ls`.

See the [full setup, PR selection, reports and cleanup guide](https://github.com/renf7/rsds-infra-local/blob/RSDSINFRA-25-local-testing/README.md) and [static behavior coverage](https://github.com/renf7/rsds-infra-local/blob/RSDSINFRA-25-local-testing/e2e/README.md). After PR #1 is merged, a normal default-branch clone will contain the implementation.
