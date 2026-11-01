#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
case "$(uname -s)" in Linux) target_os=linux;; Darwin) target_os=darwin;; *) echo 'Use build.cmd on Windows' >&2; exit 1;; esac
case "$(uname -m)" in x86_64) target_arch=amd64;; arm64|aarch64) target_arch=arm64;; *) echo 'Unsupported CPU' >&2; exit 1;; esac
mkdir -p out
docker run --rm -e GOOS="$target_os" -e GOARCH="$target_arch" -e CGO_ENABLED=0 --mount "type=bind,source=$(pwd),target=/src" -w /src golang:1.26-alpine go build -trimpath -o out/rsds-local ./cmd/rsds-local
chmod +x out/rsds-local
