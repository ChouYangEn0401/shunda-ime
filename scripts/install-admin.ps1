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

# 64-bit and 32-bit Windows PowerShell, regardless of our own bitness.
function Get-PowerShellPaths {
    $sys = 'System32'
    if (-not [Environment]::Is64BitProcess) { $sys = 'Sysnative' }
    @(
        (Join-Path $env:windir "$sys\WindowsPowerShell\v1.0\powershell.exe"),
        (Join-Path $env:windir 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe')
    )
}

try {
    Write-Host ("64-bit process: {0}" -f [Environment]::Is64BitProcess)
    $Target = Join-Path $Pime 'smartime'
    $Source = Join-Path $Repo 'backend'

    # A version installed with the Setup.exe installer: remove it with its own
    # uninstaller, so "Apps & features" does not keep a stale entry.
    $uninstKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{D0A6055C-3F02-41F7-992F-4BADAC52DDB5}_is1'
    if (Test-Path $uninstKey) {
        $uninst = ((Get-ItemProperty $uninstKey).UninstallString).Trim('"')
        if (Test-Path $uninst) {
            Write-Host "running the installed version's uninstaller: $uninst"
            Start-Process -FilePath $uninst -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait
            Start-Sleep -Seconds 3  # the uninstaller deletes itself after exiting
        }
    }

    # The running backend keeps files (smartime.db, python.exe) open.
    & (Join-Path $Repo 'installer\stop-backend.ps1') -Pime $Pime

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

    # Register only our TSF language profile under PIME's text service, in
    # both the 64-bit and the 32-bit registry views. (We used to re-run
    # regsvr32 on PIMETextService.dll, which re-registers every PIME input
    # method and failed with exit code 3 on the author's machine.)
    $manifest = Join-Path $Target 'input_methods\smartime\ime.json'
    $name = (Get-Content $manifest -Raw -Encoding UTF8 | ConvertFrom-Json).name
    $icon = Join-Path $Target 'input_methods\smartime\icons\ime.ico'
    foreach ($ps in (Get-PowerShellPaths)) {
        & $ps -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot 'tsf-profile.ps1') `
            -Action Add -Profile $ProfileGuid -Description $name -IconFile $icon
        if ($LASTEXITCODE -ne 0) { throw "TSF profile registration failed ($ps)" }
    }
    Write-Host 'admin step OK'
    Stop-Transcript | Out-Null
    exit 0
} catch {
    Write-Host "ERROR: $_"
    Stop-Transcript | Out-Null
    exit 1
}
