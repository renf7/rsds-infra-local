# Agent instructions

This Go repository is part of renf7's rsds-infra family. Read the canonical standard at https://github.com/renf7/rsds-infra-helm/blob/main/docs/security/REPOSITORY-STANDARD.md (until merged, Helm PR #4 / branch RSDSINFRA-24-security-scanning).

Keep free CodeQL Go/Actions, Semgrep CE, Trivy, dependency checks, SonarCloud quality gate, Dependabot and secret protection requirements. Trigger applicable checks on every PR commit/force-push and opened/reopened/edited/ready_for_review event. No paid tiers, token leaks, blanket exclusions or weakened gates. This repository will remain Go and tooling only: omit Java and React scanners, including SpotBugs/Find Security Bugs and React ESLint plugins. Maintain locked versions and SHA-pinned Actions. Read SCANNER-VERSIONS.md for applicability and verified native settings.

Never use a global Kubernetes context or production credentials for local tests. Require a local Docker endpoint and a dedicated rsds-local-* cluster/private kubeconfig. Cleanup only owned state; never Docker-prune or delete arbitrary paths/clusters. Preserve exact default-branch/PR source provenance, fail on mismatched served content, and do not claim missing backend coverage. Add each future backend to the manifest only when its repository and Helm values exist. Keep Jira RSDSINFRA-25 and epic RSDSINFRA-8 current.
