<#
.SYNOPSIS
    Release check for the installer, run elevated (one UAC prompt):
    install/upgrade -> uninstall -> clean install -> (optional) back to dev mode.

.DESCRIPTION
    Writes a summary to $env:TEMP\smartime-installer-test\summary.txt and the
    setup/uninstall logs next to it. Each step records what it checked:
    TSF profile in both registry views, backends.json, install folder,
    launcher running, and a typing probe (ji3 must convert to Chinese) for
    SmartIME and for Chewing (other PIME input methods must keep working).
    ASCII-only: Windows PowerShell 5.1 reads BOM-less files as ANSI.
#>
param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [switch]$RestoreDev
)

$ErrorActionPreference = 'Continue'
$out = Join-Path $env:TEMP 'smartime-installer-test'
New-Item -ItemType Directory -Force -Path $out | Out-Null
$summary = Join-Path $out 'summary.txt'
Set-Content -Path $summary -Value "installer test $(Get-Date -Format s)  setup=$Setup" -Encoding UTF8

$Pime = Join-Path ${env:ProgramFiles(x86)} 'PIME'
$App = Join-Path $Pime 'smartime'
$Tsf = Join-Path $Repo 'scripts\tsf-profile.ps1'
$Ps64 = Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Ps32 = Join-Path $env:windir 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
$DevPython = Join-Path $Repo '.venv\Scripts\python.exe'
$Chewing = '{F80736AA-28DB-423A-92C9-5540F501C939}'

function Note([string]$line) { Add-Content -Path $summary -Value $line -Encoding UTF8 }

function Probe([string]$guid) {
    $args = @('-m', 'smartime.devtools.pime_probe', '--keys', 'ji3', '--require-conversion')
    if ($guid) { $args += @('--guid', $guid) }
    $env:PYTHONPATH = Join-Path $Repo 'src'
    $o = & $DevPython @args 2>&1 | Select-Object -Last 1
    return "$o"
}

function Snapshot([string]$title) {
    Note "== $title"
    $q64 = & $Ps64 -NoProfile -ExecutionPolicy Bypass -File $Tsf -Action Query 2>&1
    $q32 = & $Ps32 -NoProfile -ExecutionPolicy Bypass -File $Tsf -Action Query 2>&1
    Note "   tsf: $q64 / $q32"
    $bj = Get-Content (Join-Path $Pime 'backends.json') -Raw
    Note ("   backends.json has smartime: " + ($bj -match '"smartime"'))
    if (Test-Path $App) {
        $item = Get-Item $App -Force
        $j = ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
        Note "   folder: present (junction=$j)"
    } else { Note '   folder: absent' }
    Note ("   launcher running: " + [bool](Get-Process PIMELauncher -ErrorAction SilentlyContinue))
}

function SetupLines([string]$log) {
    if (Test-Path $log) {
        Select-String -Path $log -Pattern '\[smartime\]' | ForEach-Object {
            $l = $_.Line
            if ($l -match 'exit code|ERROR|verified|output: (add|remove)') { Note ('   ' + $l.Substring([Math]::Min(23, $l.Length))) }
        }
    }
}

# 1. install / upgrade
$log1 = Join-Path $out 'setup-1.log'
$p = Start-Process -FilePath $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$log1`"" -Wait -PassThru
Note "== 1. install/upgrade: exit $($p.ExitCode)"
SetupLines $log1
Start-Sleep -Seconds 2
Snapshot '1. after install'
Note ('   probe SmartIME: ' + (Probe ''))

# 2. uninstall
$unins = Join-Path $App 'unins000.exe'
$log2 = Join-Path $out 'uninstall.log'
$p = Start-Process -FilePath $unins -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$log2`"" -Wait -PassThru
Note "== 2. uninstall: exit $($p.ExitCode)"
SetupLines $log2
Start-Sleep -Seconds 4  # the uninstaller finishes deleting itself, launcher restarts
Snapshot '2. after uninstall'
Note ('   probe chewing (must still work): ' + (Probe $Chewing))

# 3. clean install
$log3 = Join-Path $out 'setup-2.log'
$p = Start-Process -FilePath $Setup -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$log3`"" -Wait -PassThru
Note "== 3. clean install: exit $($p.ExitCode)"
SetupLines $log3
Start-Sleep -Seconds 2
Snapshot '3. after clean install'
Note ('   probe SmartIME: ' + (Probe ''))
Note ('   probe chewing: ' + (Probe $Chewing))

# 4. back to the developer setup (junction to the repo)
if ($RestoreDev) {
    & $Ps64 -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo 'scripts\install-admin.ps1') -Repo $Repo -Pime $Pime -Mode Dev | Out-Null
    & (Join-Path $Pime 'PIMELauncher.exe') /quit
    Start-Sleep -Milliseconds 800
    Start-Process -FilePath (Join-Path $env:windir 'explorer.exe') -ArgumentList "`"$(Join-Path $Pime 'PIMELauncher.exe')`""
    Start-Sleep -Seconds 3
    Snapshot '4. back to dev mode'
    Note ('   probe SmartIME: ' + (Probe ''))
}
Note 'done'
