<#
.SYNOPSIS
    Build the Windows one-dir bundle for the Fluke Community desktop app and,
    optionally, an Inno Setup installer.

.DESCRIPTION
    Runs PyInstaller against packaging/fluke-desktop.spec, then (if Inno Setup's
    ISCC.exe is available) compiles packaging/windows/installer.iss into a
    single-file installer under dist/installer.

.EXAMPLE
    pwsh packaging/windows/build_windows.ps1
    pwsh packaging/windows/build_windows.ps1 -SkipInstaller
#>
[CmdletBinding()]
param(
    [switch]$SkipInstaller
)

$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $RepoRoot

Write-Host "==> Building PyInstaller bundle" -ForegroundColor Cyan
python -m PyInstaller packaging/fluke-desktop.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed (exit $LASTEXITCODE)." }

$ExePath = Join-Path $RepoRoot "dist\FlukeCommunity\FlukeCommunity.exe"
if (-not (Test-Path $ExePath)) { throw "Expected executable not found: $ExePath" }

Write-Host "==> Running smoke test" -ForegroundColor Cyan
python packaging/smoke_test.py
if ($LASTEXITCODE -ne 0) { throw "Smoke test failed (exit $LASTEXITCODE)." }

if ($SkipInstaller) {
    Write-Host "==> Skipping installer step (-SkipInstaller)." -ForegroundColor Yellow
    exit 0
}

$Iscc = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
if (-not $Iscc) {
    $DefaultIscc = "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    if (Test-Path $DefaultIscc) { $Iscc = $DefaultIscc } else { $Iscc = $null }
} else {
    $Iscc = $Iscc.Source
}

if (-not $Iscc) {
    Write-Host "==> Inno Setup (ISCC.exe) not found; skipping installer." -ForegroundColor Yellow
    Write-Host "    Install from https://jrsoftware.org/isdl.php to build the installer." -ForegroundColor Yellow
    exit 0
}

Write-Host "==> Compiling Inno Setup installer" -ForegroundColor Cyan
& $Iscc "packaging\windows\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed (exit $LASTEXITCODE)." }

Write-Host "==> Done. Artifacts in dist/ and dist/installer/." -ForegroundColor Green
