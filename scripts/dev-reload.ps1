<#
.SYNOPSIS
    Development helper: reload the SmartIME backend after code changes,
    optionally rebuilding the lexicon, then verify with the launcher probe.

.DESCRIPTION
    The backend (and therefore smartime.db) stays open while any app uses
    the IME, and PIMELauncher restarts a killed backend immediately. So we
    stop the launcher, do the work, and start it again through explorer.exe
    (so it does not belong to this console). No administrator rights needed.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\dev-reload.ps1 -Rebuild
#>
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$Pime = Join-Path ${env:ProgramFiles(x86)} 'PIME'
$launcher = Join-Path $Pime 'PIMELauncher.exe'

Write-Host '==> Stopping PIMELauncher (all PIME backends)' -ForegroundColor Cyan
Start-Process -FilePath $launcher -ArgumentList '/quit' -Wait
$deadline = (Get-Date).AddSeconds(10)
while ((Get-Process PIMELauncher -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
# the backend (python.exe) and an open settings window (pythonw.exe) both
# keep smartime.db open
Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object { $_.ExecutablePath -like '*PIME\smartime\runtime\python*.exe' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

$failed = $null
if ($Rebuild) {
    Write-Host '==> Rebuilding the lexicon' -ForegroundColor Cyan
    Push-Location $Repo
    try {
        & (Join-Path $Repo '.venv\Scripts\python.exe') tools\build_data.py
        if ($LASTEXITCODE -ne 0) { $failed = 'lexicon build failed' }
    } finally { Pop-Location }
}

Write-Host '==> Starting PIMELauncher' -ForegroundColor Cyan
Start-Process -FilePath 'explorer.exe' -ArgumentList "`"$launcher`""
$deadline = (Get-Date).AddSeconds(10)
while (-not (Get-Process PIMELauncher -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
Start-Sleep -Seconds 1
if ($failed) { throw $failed }

Write-Host '==> Verifying' -ForegroundColor Cyan
& (Join-Path $Repo '.venv\Scripts\python.exe') -m smartime.devtools.pime_probe --require-conversion
if ($LASTEXITCODE -ne 0) { throw 'probe failed' }
