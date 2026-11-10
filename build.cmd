@echo off
setlocal
cd /d "%~dp0"
if not exist out mkdir out
docker run --rm -e GOOS=windows -e GOARCH=amd64 -e CGO_ENABLED=0 --mount "type=bind,source=%CD%,target=/src" -w /src golang:1.26-alpine go build -trimpath -o out/rsds-local.exe ./cmd/rsds-local
exit /b %ERRORLEVEL%
