# Build and run the API stack in Docker. Requires Docker Desktop (Linux engine) running.
# Usage: .\scripts\docker_up.ps1 [-Migrate] [-Seed] [-SkipBuild]

param(
    [switch]$Migrate,
    [switch]$Seed,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env")) {
    Write-Error "Missing .env in $Root (need DATABASE_URL and other settings)."
}

function Wait-DockerDaemon {
    param([int]$MaxSeconds = 180)
    $deadline = (Get-Date).AddSeconds($MaxSeconds)
    while ((Get-Date) -lt $deadline) {
        docker info 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { return $true }
        Write-Host "Waiting for Docker daemon..."
        Start-Sleep 5
    }
    return $false
}

if (-not (Wait-DockerDaemon)) {
    Write-Error @"
Docker daemon is not ready. On Windows:
  1. Open Docker Desktop and wait until it shows 'Engine running'.
  2. If it stays broken: Docker Desktop -> Troubleshoot -> Restart / Reset.
  3. Then run: .\scripts\docker_up.ps1
"@
}

$composeArgs = @("compose", "up", "-d")
if (-not $SkipBuild) { $composeArgs += "--build" }
docker @composeArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "Waiting for backend health..."
$healthDeadline = (Get-Date).AddSeconds(120)
$ok = $false
while ((Get-Date) -lt $healthDeadline) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 5
        if ($r.status -eq "ok") { $ok = $true; break }
    } catch { }
    Start-Sleep 3
}
if (-not $ok) {
    Write-Warning "Health check timed out. Logs: docker compose logs backend --tail 50"
} else {
    Write-Host "Backend healthy at http://127.0.0.1:8000"
}

if ($Migrate) {
    Write-Host "Running policy schema migration (drops policy/claim tables)..."
    docker compose exec -T backend python -m scripts.migrate_policy_schema
}
if ($Seed) {
    Write-Host "Seeding healthcare policy and test users..."
    docker compose exec -T backend python -m scripts.seed_healthcare_policy
}

Write-Host "Done. API: http://127.0.0.1:8000/docs"
