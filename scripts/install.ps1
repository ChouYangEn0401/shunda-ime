<#
.SYNOPSIS
    Install SmartIME (zhi-hui shu-ru-fa) as a PIME backend on this PC.

.DESCRIPTION
    Runs as the normal user and asks for administrator rights only for the
    steps that need them (writing under Program Files, registering the TSF DLL).

    Steps:
      1. Install PIME 1.3.0 if it is missing.
      2. Make sure the lexicon is built (data/generated/smartime.db).
      3. Download a private embeddable Python into backend/runtime.
      4. [admin] Link (-Dev) or copy the backend into <PIME>\smartime,
         add it to backends.json, re-register PIMETextService.dll.
      5. Restart PIMELauncher (as the user) and add the IME to the
         Chinese (Taiwan) keyboard list.

    User data (settings, learned words) lives in %APPDATA%\SmartIME and is
    never touched by install or uninstall.

.PARAMETER Dev
    Developer mode: <PIME>\smartime becomes a junction to this repository's
    backend folder, so code changes apply after "Restart PIME" in the tray.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\install.ps1 -Dev
#>
[CmdletBinding()]
param(
    [switch]$Dev,
    [switch]$SkipLanguageList
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path -Parent $PSScriptRoot
$PythonVersion = '3.13.16'
$PimeSetupUrl = 'https://github.com/EasyIME/PIME/releases/download/v1.3.0-stable/PIME-1.3.0-stable-setup.exe'
$PimeClsid = '{35F67E9D-A54D-4177-9697-8B0AB71A9E04}'
$ProfileGuid = '{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}'
$Pime = Join-Path ${env:ProgramFiles(x86)} 'PIME'

function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# 1. PIME -------------------------------------------------------------------
if (-not (Test-Path (Join-Path $Pime 'PIMELauncher.exe'))) {
    Step 'PIME not found; downloading the PIME 1.3.0 installer'
    $setup = Join-Path $env:TEMP 'PIME-1.3.0-stable-setup.exe'
    Invoke-WebRequest -Uri $PimeSetupUrl -OutFile $setup -UseBasicParsing
    Step 'Running the PIME installer (accept the UAC prompt; the defaults are fine)'
    Start-Process -FilePath $setup -Wait
    if (-not (Test-Path (Join-Path $Pime 'PIMELauncher.exe'))) {
        throw "PIME was not installed to $Pime"
    }
}

# 2. Lexicon ----------------------------------------------------------------
$Db = Join-Path $Repo 'data\generated\smartime.db'
if (-not (Test-Path $Db)) {
    Step 'Building the lexicon (first time only)'
    $venvPython = Join-Path $Repo '.venv\Scripts\python.exe'
    if (-not (Test-Path $venvPython)) {
        throw 'Create the development environment first: py -3.13 -m venv .venv; .venv\Scripts\python -m pip install -r requirements.txt'
    }
    Push-Location $Repo
    try { & $venvPython tools\build_data.py } finally { Pop-Location }
    if (-not (Test-Path $Db)) { throw 'lexicon build failed' }
}

# 3. Private Python runtime ---------------------------------------------------
$Runtime = Join-Path $Repo 'backend\runtime'
$RuntimePython = Join-Path $Runtime 'python.exe'
if (-not (Test-Path $RuntimePython)) {
    Step "Downloading embeddable Python $PythonVersion"
    $zip = Join-Path $env:TEMP "python-$PythonVersion-embed-amd64.zip"
    $url = "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip"
    Invoke-WebRequest -Uri $url -OutFile $zip -UseBasicParsing
    Expand-Archive -Path $zip -DestinationPath $Runtime -Force
}
# The ._pth file defines sys.path for the embeddable build; add the backend
# folder (..) so server.py's directory is importable.
$pth = Get-ChildItem -Path $Runtime -Filter 'python*._pth' | Select-Object -First 1
$pthLines = Get-Content $pth.FullName
if ($pthLines -notcontains '..') {
    Add-Content -Path $pth.FullName -Value '..' -Encoding ASCII
}

# 4. Admin part ---------------------------------------------------------------
$mode = 'Copy'
if ($Dev) { $mode = 'Dev' }
Step "Installing into $Pime\smartime ($mode mode) - accept the UAC prompt"
$adminArgs = @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass',
    '-File', "`"$PSScriptRoot\install-admin.ps1`"",
    '-Repo', "`"$Repo`"", '-Pime', "`"$Pime`"", '-Mode', $mode
)
$p = Start-Process -FilePath 'powershell.exe' -ArgumentList $adminArgs -Verb RunAs -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "administrator step failed (exit code $($p.ExitCode)); see $env:TEMP\smartime-install-admin.log" }

# 5. Restart PIMELauncher as the current user ------------------------------
# The launcher reads backends.json and every ime.json only at startup.
# Start it through explorer.exe so it is not a child of this console (or of
# a terminal/job object that may be closed later).
Step 'Restarting PIMELauncher'
$launcher = Join-Path $Pime 'PIMELauncher.exe'
Start-Process -FilePath $launcher -ArgumentList '/quit' -Wait -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
Start-Process -FilePath 'explorer.exe' -ArgumentList "`"$launcher`""
$deadline = (Get-Date).AddSeconds(10)
while (-not (Get-Process PIMELauncher -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
if (-not (Get-Process PIMELauncher -ErrorAction SilentlyContinue)) { throw 'PIMELauncher did not start' }
Start-Sleep -Seconds 1

# 6. Verify: talk to the launcher like an application would ---------------
Step 'Verifying: launcher -> SmartIME backend -> engine'
$srcDir = Join-Path $Repo 'src'
$probe = "import sys; sys.path.insert(0, r'$srcDir'); from smartime.devtools.pime_probe import main; sys.exit(main(['--keys', 'ji3ap7', '--require-conversion']))"
& $RuntimePython -c $probe
if ($LASTEXITCODE -ne 0) { throw 'verification failed: the launcher could not reach the SmartIME backend' }

# 7. Keyboard list ---------------------------------------------------------
if (-not $SkipLanguageList) {
    $tip = "0404:$PimeClsid$ProfileGuid"
    $list = Get-WinUserLanguageList
    $zh = $list | Where-Object { $_.LanguageTag -eq 'zh-Hant-TW' } | Select-Object -First 1
    if ($null -eq $zh) {
        $list.Add('zh-Hant-TW')
        $zh = $list | Where-Object { $_.LanguageTag -eq 'zh-Hant-TW' } | Select-Object -First 1
    }
    if ($zh.InputMethodTips -notcontains $tip) {
        Step 'Adding SmartIME to the Chinese (Taiwan) keyboard list'
        $zh.InputMethodTips.Add($tip)
        Set-WinUserLanguageList -LanguageList $list -Force
    }
}

Write-Host ''
Write-Host 'Done. Press Win+Space and pick the new input method (icon: blue square).' -ForegroundColor Green
Write-Host 'Logs: %APPDATA%\SmartIME\logs\backend.log'
