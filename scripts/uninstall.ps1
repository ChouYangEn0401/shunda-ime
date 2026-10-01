<#
.SYNOPSIS
    Remove SmartIME from PIME. Settings and learned words in
    %APPDATA%\SmartIME are kept (delete that folder yourself if wanted).
#>
$ErrorActionPreference = 'Stop'
$PimeClsid = '{35F67E9D-A54D-4177-9697-8B0AB71A9E04}'
$ProfileGuid = '{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}'
$Pime = Join-Path ${env:ProgramFiles(x86)} 'PIME'

$tip = "0404:$PimeClsid$ProfileGuid"
$list = Get-WinUserLanguageList
foreach ($lang in $list) {
    if ($lang.InputMethodTips -contains $tip) { [void]$lang.InputMethodTips.Remove($tip) }
}
Set-WinUserLanguageList -LanguageList $list -Force

$adminArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', "`"$PSScriptRoot\uninstall-admin.ps1`"", '-Pime', "`"$Pime`"")
$p = Start-Process -FilePath 'powershell.exe' -ArgumentList $adminArgs -Verb RunAs -Wait -PassThru
if ($p.ExitCode -ne 0) { throw "administrator step failed; see $env:TEMP\smartime-uninstall-admin.log" }

$launcher = Join-Path $Pime 'PIMELauncher.exe'
Start-Process -FilePath $launcher -ArgumentList '/quit' -Wait -ErrorAction SilentlyContinue
Start-Sleep -Milliseconds 800
# via explorer.exe so the launcher is not a child of this console
Start-Process -FilePath 'explorer.exe' -ArgumentList "`"$launcher`""
Write-Host 'SmartIME removed.' -ForegroundColor Green
