<#
.SYNOPSIS
    Elevated half of install.ps1. Do not run directly.
#>
param(
    [Parameter(Mandatory = $true)][string]$Repo,
    [Parameter(Mandatory = $true)][string]$Pime,
    [ValidateSet('Dev', 'Copy')][string]$Mode = 'Copy'
)

$ErrorActionPreference = 'Stop'
$ProfileGuid = '{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}'
Start-Transcript -Path (Join-Path $env:TEMP 'smartime-install-admin.log') -Force | Out-Null

try {
    $Target = Join-Path $Pime 'smartime'
    $Source = Join-Path $Repo 'backend'

    # Remove a previous install, but only if it is ours.
    if (Test-Path $Target) {
        $item = Get-Item $Target -Force
        $isJunction = ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        if ($isJunction) {
            cmd /c rmdir "$Target" | Out-Null
        } else {
            $manifest = Join-Path $Target 'input_methods\smartime\ime.json'
            if (-not ((Test-Path $manifest) -and ((Get-Content $manifest -Raw) -match [regex]::Escape($ProfileGuid)))) {
                throw "$Target exists and does not look like a SmartIME install; refusing to delete it"
            }
            Remove-Item -Recurse -Force $Target
        }
    }

    if ($Mode -eq 'Dev') {
        New-Item -ItemType Junction -Path $Target -Target $Source | Out-Null
    } else {
        robocopy $Source $Target /E /NFL /NDL /NJH /NJS /XD __pycache__ | Out-Null
        robocopy (Join-Path $Repo 'src') (Join-Path $Target 'app\src') /E /NFL /NDL /NJH /NJS /XD __pycache__ | Out-Null
        $dataDir = Join-Path $Target 'app\data\generated'
        New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
        Copy-Item (Join-Path $Repo 'data\generated\smartime.db') $dataDir -Force
        # robocopy uses exit codes < 8 for success
        $global:LASTEXITCODE = 0
    }

    $python = Join-Path $Target 'runtime\python.exe'
    & $python (Join-Path $Repo 'scripts\pime_backends.py') add $Pime
    if ($LASTEXITCODE -ne 0) { throw 'failed to update backends.json' }

    # Re-registering makes PIME scan every backend's input_methods folder and
    # register a TSF language profile for each ime.json it finds.
    foreach ($arch in 'x64', 'x86') {
        $dll = Join-Path $Pime "$arch\PIMETextService.dll"
        if (Test-Path $dll) {
            $r = Start-Process -FilePath 'regsvr32.exe' -ArgumentList '/s', "`"$dll`"" -Wait -PassThru
            if ($r.ExitCode -ne 0) { throw "regsvr32 failed for $dll ($($r.ExitCode))" }
        }
    }
    Write-Host 'admin step OK'
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "ERROR: $_"
    Stop-Transcript | Out-Null
    exit 1
}
