<#
.SYNOPSIS
    Elevated half of uninstall.ps1. Do not run directly.
#>
param([Parameter(Mandatory = $true)][string]$Pime)

$ErrorActionPreference = 'Stop'
$ProfileGuid = '{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}'
Start-Transcript -Path (Join-Path $env:TEMP 'smartime-uninstall-admin.log') -Force | Out-Null
try {
    $Target = Join-Path $Pime 'smartime'
    $python = Join-Path $Target 'runtime\python.exe'
    $helper = Join-Path $PSScriptRoot 'pime_backends.py'
    if (Test-Path $python) {
        & $python $helper remove $Pime
    }

    # Unregister every PIME profile, then re-register: the remaining backends
    # are registered again, ours is gone.
    foreach ($arch in 'x64', 'x86') {
        $dll = Join-Path $Pime "$arch\PIMETextService.dll"
        if (Test-Path $dll) {
            Start-Process -FilePath 'regsvr32.exe' -ArgumentList '/s', '/u', "`"$dll`"" -Wait | Out-Null
        }
    }

    if (Test-Path $Target) {
        $item = Get-Item $Target -Force
        if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
            cmd /c rmdir "$Target" | Out-Null
        } else {
            $manifest = Join-Path $Target 'input_methods\smartime\ime.json'
            if ((Test-Path $manifest) -and ((Get-Content $manifest -Raw) -match [regex]::Escape($ProfileGuid))) {
                Remove-Item -Recurse -Force $Target
            }
        }
    }

    foreach ($arch in 'x64', 'x86') {
        $dll = Join-Path $Pime "$arch\PIMETextService.dll"
        if (Test-Path $dll) {
            Start-Process -FilePath 'regsvr32.exe' -ArgumentList '/s', "`"$dll`"" -Wait | Out-Null
        }
    }
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "ERROR: $_"
    Stop-Transcript | Out-Null
    exit 1
}
