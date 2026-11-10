param([Parameter(Mandatory)][string]$RunDirectory)
$ErrorActionPreference = 'Stop'
$report = Get-Content -LiteralPath (Join-Path $RunDirectory 'report.json') -Raw | ConvertFrom-Json
if ($report.owner -ne 'renf7/rsds-infra-local' -or $report.cluster -notmatch '^rsds-local-[a-z0-9-]+$' -or
    $report.identityProviderMode -ne 'local-protocol-fixture' -or -not $report.authenticationEnabled) {
    throw 'Requires an owned rsds-infra-local authentication fixture run.'
}
$dockerContext = $report.dockerContext
$endpoint = docker context inspect $dockerContext --format '{{.Endpoints.docker.Host}}'
if ($LASTEXITCODE -ne 0 -or $endpoint -notmatch '^(npipe://|unix://)') { throw 'Local Docker endpoint required.' }
$kubeArgs = @('--kubeconfig', $report.kubeconfig, '--context', "kind-$($report.cluster)", '-n', 'rsds-local-test')
function Invoke-Kube([string[]]$Arguments) {
    $output = & kubectl @kubeArgs @Arguments
    if ($LASTEXITCODE -ne 0) { throw "kubectl failed: $($Arguments[0])" }
    return $output
}
$configName = 'rsds-local-provider-visibility'
$original = Invoke-Kube @('get', 'configmap', $configName, '-o', 'json') | ConvertFrom-Json
$before = Invoke-Kube @('get', 'pods', '-l', 'app=rsds-local-auth', '-o', 'json') | ConvertFrom-Json
if ($before.items.Count -ne 1) { throw 'Expected one auth pod.' }
$artifact = Join-Path $RunDirectory ('visibility-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $artifact | Out-Null
$artifact = (Resolve-Path $artifact).Path
$browserUser = @()
if (-not $IsWindows) { $browserUser = @('--user', "$(id -u):$(id -g)") }
$root = Split-Path $PSScriptRoot -Parent
$image = 'rsds-local/visibility-e2e:local'
docker --context $dockerContext build -t $image (Join-Path $root 'e2e')
if ($LASTEXITCODE -ne 0) { throw 'Browser image build failed.' }
$container = "$($report.cluster)-visibility-$([guid]::NewGuid().ToString('N').Substring(0,8))"
function Set-Policy([string]$Value) {
    $patch = Join-Path $artifact 'patch.json'
    @{data=@{'visible-providers'=$Value}} | ConvertTo-Json -Compress | Set-Content -LiteralPath $patch -Encoding utf8
    Invoke-Kube @('patch', 'configmap', $configName, '--type', 'merge', '--patch-file', $patch) | Out-Null
}
$created = $false
try {
    docker --context $dockerContext run -d --name $container @browserUser --network kind --cap-drop ALL --security-opt no-new-privileges --shm-size 256m `
        --mount "type=bind,source=$artifact,target=/control" `
        --mount "type=bind,source=$(Join-Path $root 'e2e/test_visibility.py'),target=/app/test_visibility.py,readonly" `
        --env "BASE_URL=http://$($report.cluster)-control-plane:30080" $image python /app/test_visibility.py
    if ($LASTEXITCODE -ne 0) { throw 'Browser startup failed.' }
    $created = $true
    $last = -1
    $deadline = (Get-Date).AddMinutes(14)
    while ((Get-Date) -lt $deadline) {
        $request = Join-Path $artifact 'request.json'
        if (Test-Path -LiteralPath $request) {
            $next = Get-Content -LiteralPath $request -Raw | ConvertFrom-Json
            if ($next.index -gt $last) {
                Set-Policy $next.value
                Set-Content -LiteralPath (Join-Path $artifact "applied-$($next.index)") -Value 'ok'
                $last = $next.index
            }
        }
        $running = docker --context $dockerContext inspect --format '{{.State.Running}}' $container
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect browser.' }
        if ($running -eq 'false') { break }
        Start-Sleep -Seconds 1
    }
    $code = docker --context $dockerContext inspect --format '{{.State.ExitCode}}' $container
    if ($running -ne 'false' -or $code -ne '0') { throw 'Runtime visibility browser test failed/timed out.' }
    $after = Invoke-Kube @('get', 'pods', '-l', 'app=rsds-local-auth', '-o', 'json') | ConvertFrom-Json
    if ($after.items.Count -ne 1 -or $before.items[0].metadata.uid -ne $after.items[0].metadata.uid -or
        $before.items[0].status.containerStatuses[0].restartCount -ne $after.items[0].status.containerStatuses[0].restartCount) {
        throw 'Auth pod restarted during runtime policy test.'
    }
    $result = Get-Content -LiteralPath (Join-Path $artifact 'result.json') -Raw | ConvertFrom-Json
    if (-not $result.passed -or $result.stages -ne 4) { throw 'Incomplete browser result.' }
    Write-Host "PASS: four runtime policy changes, EN/PL browsers, session preserved, no auth restart. Evidence: $artifact"
} finally {
    try { Set-Policy $original.data.'visible-providers' } finally {
        if ($created) {
            docker --context $dockerContext logs $container 2>&1 | Set-Content -LiteralPath (Join-Path $artifact 'browser.log')
            docker --context $dockerContext rm -f $container | Out-Null
        }
    }
}
