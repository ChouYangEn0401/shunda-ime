<#
.SYNOPSIS
    Elevated half of uninstall.ps1. Do not run directly.
#>
param([Parameter(Mandatory = $true)][string]$Pime)

$ErrorActionPreference = 'Stop'
$ProfileGuid = '{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}'
Start-Transcript -Path (Join-Path $env:TEMP 'smartime-uninstall-admin.log') -Force | Out-Null

function Get-PowerShellPaths {
    $sys = 'System32'
    if (-not [Environment]::Is64BitProcess) { $sys = 'Sysnative' }
    @(
        (Join-Path $env:windir "$sys\WindowsPowerShell\v1.0\powershell.exe"),
        (Join-Path $env:windir 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe')
    )
}

try {
    $Target = Join-Path $Pime 'smartime'

    # Remove only our TSF profile; other PIME input methods stay registered.
    foreach ($ps in (Get-PowerShellPaths)) {
        & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'tsf-profile.ps1') `
            -Action Remove -Profile $ProfileGuid
    }

    $python = Join-Path $Target 'runtime\python.exe'
    if (Test-Path $python) {
        & $python (Join-Path $PSScriptRoot 'pime_backends.py') remove $Pime
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
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "ERROR: $_"
    Stop-Transcript | Out-Null
    exit 1
}
