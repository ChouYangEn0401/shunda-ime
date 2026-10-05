<#
.SYNOPSIS
    Release check for the installer, run elevated (one UAC prompt). Walks the
    installer through every situation a user's PC can be in and checks the
    result after each step.

.DESCRIPTION
    Steps (1 and 2 only when the official PIME is installed):
      1. shared   - install next to the official PIME (its input methods stay)
      2. takeover - install with the "takeover" task (PIME's own input
                    methods are removed, only ours is left)
      3. uninstall - everything we installed must be gone
      4. clean    - install on a PC without any PIME (like a new computer);
                    with -FreshUserData also without %APPDATA%\SmartIME
      5. upgrade  - run the same installer again over the installation
    After each step the summary records: setup exit code and errors, the
    TSF profiles under PIME's text service (64/32-bit), COM registration,
    backends.json, PIME files, the autostart entry, pending deletes under
    PIME, the keyboard list, the launcher, and a typing probe (ji3 -> Chinese).
    Summary: $env:TEMP\smartime-installer-test\summary.txt (+ setup logs).
    Never sends keyboard input. ASCII-only: Windows PowerShell 5.1 reads
    BOM-less files as ANSI.

.PARAMETER FreshUserData
    During steps 4-5, move %APPDATA%\SmartIME aside (first-run test) and put
    it back at the end. The backup folder name is written to the summary.
#>
param(
    [Parameter(Mandatory = $true)][string]$Setup,
    [string]$Repo = (Split-Path -Parent $PSScriptRoot),
    [switch]$FreshUserData,
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
$Clsid = '{35F67E9D-A54D-4177-9697-8B0AB71A9E04}'
$Tip = "0404:$Clsid{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}"
$Chewing = '{F80736AA-28DB-423A-92C9-5540F501C939}'
$OfficialKey = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\PIME'
$UserData = Join-Path $env:APPDATA 'SmartIME'
$step = 0

function Note([string]$line) { Add-Content -Path $summary -Value $line -Encoding UTF8 }

function Probe([string]$guid) {
    $a = @('-m', 'smartime.devtools.pime_probe', '--keys', 'ji3', '--require-conversion')
    if ($guid) { $a += @('--guid', $guid) }
    $env:PYTHONPATH = Join-Path $Repo 'src'
    $o = & $DevPython @a 2>&1 | Select-Object -Last 1
    return "$o"
}

function Profiles([string]$root) {
    $k = "$root\Microsoft\CTF\TIP\$Clsid\LanguageProfile\0x00000404"
    if (-not (Test-Path $k)) { return '(none)' }
    $names = Get-ChildItem $k | ForEach-Object { (Get-ItemProperty $_.PSPath).Description }
    return ($names -join ', ')
}

function Snapshot([string]$title) {
    Note "== $title"
    Note ("   official PIME installed: " + (Test-Path $OfficialKey))
    Note ("   TSF profiles 64: " + (Profiles 'HKLM:\SOFTWARE') + "  |  32: " + (Profiles 'HKLM:\SOFTWARE\WOW6432Node'))
    $q64 = & $Ps64 -NoProfile -ExecutionPolicy Bypass -File $Tsf -Action Query 2>&1
    $q32 = & $Ps32 -NoProfile -ExecutionPolicy Bypass -File $Tsf -Action Query 2>&1
    Note "   our profile: $q64 / $q32"
    $com64 = (Get-ItemProperty "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\Classes\CLSID\$Clsid\InprocServer32" -ErrorAction SilentlyContinue).'(default)'
    $com32 = (Get-ItemProperty "Registry::HKEY_LOCAL_MACHINE\SOFTWARE\WOW6432Node\Classes\CLSID\$Clsid\InprocServer32" -ErrorAction SilentlyContinue).'(default)'
    Note "   COM 64: $com64  |  COM 32: $com32"
    $bj = Join-Path $Pime 'backends.json'
    if (Test-Path $bj) {
        $names = (Get-Content $bj -Raw | ConvertFrom-Json) | ForEach-Object { $_.name }
        Note ("   backends.json: " + ($names -join ', '))
    } else { Note '   backends.json: (none)' }
    if (Test-Path $Pime) {
        $files = Get-ChildItem $Pime -Recurse -Depth 1 -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -notlike "$App\*" } |
            ForEach-Object { $_.FullName.Substring($Pime.Length + 1) }
        Note ("   PIME folder: " + ($files -join ', '))
    } else { Note '   PIME folder: (none)' }
    $run = (Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue).PIMELauncher
    Note "   autostart: $run"
    $ops = @((Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager' -ErrorAction SilentlyContinue).PendingFileRenameOperations)
    $mine = @($ops | Where-Object { $_ -and $_ -like '*\PIME\*' })
    Note ("   pending restart operations under PIME: " + ($mine -join ' ; '))
    $core = @('PIMELauncher.exe', 'x64\PIMETextService.dll', 'x86\PIMETextService.dll') |
        ForEach-Object { ('\??\' + (Join-Path $Pime $_)).ToLowerInvariant() }
    $doomed = $false
    for ($i = 0; $i + 1 -lt $ops.Count; $i += 2) {
        if ($ops[$i] -and $ops[$i + 1] -eq '' -and $core -contains ($ops[$i] -replace '^\*\d+', '').ToLowerInvariant()) { $doomed = $true }
    }
    Note "   a PIME core file will be deleted at restart: $doomed"
    $zh = Get-WinUserLanguageList | Where-Object { $_.LanguageTag -eq 'zh-Hant-TW' } | Select-Object -First 1
    Note ("   keyboard list has SmartIME: " + ($null -ne $zh -and $zh.InputMethodTips -contains $Tip))
    Note ("   launcher running: " + [bool](Get-Process PIMELauncher -ErrorAction SilentlyContinue))
}

function SetupLines([string]$log) {
    if (Test-Path $log) {
        Select-String -Path $log -Pattern '\[smartime\]|Need to restart' | ForEach-Object {
            $l = $_.Line
            if ($l -match 'exit code|ERROR|verified|mode:|takeover|output: (add|remove|only)|Need to restart|renamed|cancel') {
                Note ('   ' + $l.Substring([Math]::Min(23, $l.Length)))
            }
        }
    }
}

function RunSetup([string]$title, [string[]]$extra) {
    $script:step++
    $log = Join-Path $out ("step{0}.log" -f $script:step)
    $a = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$log`"") + $extra
    $p = Start-Process -FilePath $Setup -ArgumentList $a -Wait -PassThru
    Note "== $($script:step). $title : setup exit $($p.ExitCode)"
    SetupLines $log
    Start-Sleep -Seconds 2
    Snapshot "$($script:step). after $title"
    Note ('   probe SmartIME: ' + (Probe ''))
}

function Uninstall([string]$title) {
    $script:step++
    $log = Join-Path $out ("step{0}-uninstall.log" -f $script:step)
    $unins = Join-Path $App 'unins000.exe'
    $p = Start-Process -FilePath $unins -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/LOG=`"$log`"" -Wait -PassThru
    Note "== $($script:step). $title : exit $($p.ExitCode)"
    SetupLines $log
    Start-Sleep -Seconds 4  # the uninstaller deletes itself after exiting
    Snapshot "$($script:step). after $title"
}

function StopLauncher {
    $launcher = Join-Path $Pime 'PIMELauncher.exe'
    if (Test-Path $launcher) { Start-Process -FilePath $launcher -ArgumentList '/quit' -Wait -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 1
    Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.ExecutablePath -like '*PIME\smartime\runtime\python*.exe' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

function StartLauncher {
    Start-Process -FilePath (Join-Path $env:windir 'explorer.exe') -ArgumentList "`"$(Join-Path $Pime 'PIMELauncher.exe')`""
    Start-Sleep -Seconds 3
}

Snapshot '0. before'

if (Test-Path $OfficialKey) {
    RunSetup 'install next to the official PIME (shared)' @()
    Note ('   probe chewing (must still work): ' + (Probe $Chewing))
    RunSetup 'install with takeover' @('/TASKS="takeover"')
    Note ('   probe chewing (must be gone): ' + (Probe $Chewing))
}

Uninstall 'uninstall'

# Like PIME's own uninstaller when apps still had the DLL loaded: a file at
# the DLL path whose deletion is queued for the next restart. The clean
# install must cancel that queued delete and replace the file.
Add-Type -Namespace SmartImeTest -Name Native -MemberDefinition @'
[DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
public static extern bool MoveFileEx(string existing, string newName, int flags);
'@
$fake = Join-Path $Pime 'x64\PIMETextService.dll'
New-Item -ItemType Directory -Force -Path (Split-Path $fake) | Out-Null
Set-Content -Path $fake -Value 'not the real DLL' -Encoding ASCII
$queued = [SmartImeTest.Native]::MoveFileEx($fake, $null, 4)
Note "   simulated leftover DLL with a delete queued for restart: $queued"

$backup = $null
if ($FreshUserData -and (Test-Path $UserData)) {
    $backup = "$UserData.installer-test-$(Get-Date -Format yyyyMMddHHmmss)"
    Move-Item -LiteralPath $UserData -Destination $backup
    Note "   user data moved aside to $backup"
}

RunSetup 'clean install (no PIME on the PC)' @()
if ($FreshUserData) { Note ("   first run created user data: " + (Test-Path (Join-Path $UserData 'user.db'))) }
RunSetup 'upgrade over itself' @()

if ($backup) {
    StopLauncher
    Remove-Item -LiteralPath $UserData -Recurse -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $backup -Destination $UserData
    StartLauncher
    Note "== user data restored from $backup"
    Note ('   probe SmartIME: ' + (Probe ''))
}

# back to the developer setup (junction to the repo)
if ($RestoreDev) {
    & $Ps64 -NoProfile -ExecutionPolicy Bypass -File (Join-Path $Repo 'scripts\install-admin.ps1') -Repo $Repo -Pime $Pime -Mode Dev | Out-Null
    StopLauncher
    StartLauncher
    Snapshot 'back to dev mode'
    Note ('   probe SmartIME: ' + (Probe ''))
}
Note 'done'
