<#
.SYNOPSIS
    Add or remove SmartIME in the current user's Chinese (Taiwan) keyboard list.

.DESCRIPTION
    Run as the signed-in user (the installer uses runasoriginaluser), because
    the keyboard list is a per-user setting. Kept ASCII-only: Windows
    PowerShell 5.1 reads BOM-less files with the ANSI code page.
#>
param(
    [ValidateSet('Add', 'Remove')][string]$Action = 'Add',
    [string]$Tip = '0404:{35F67E9D-A54D-4177-9697-8B0AB71A9E04}{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}'
)

$ErrorActionPreference = 'Stop'
try {
    $list = Get-WinUserLanguageList
    $zh = $list | Where-Object { $_.LanguageTag -eq 'zh-Hant-TW' } | Select-Object -First 1
    if ($Action -eq 'Add') {
        if ($null -eq $zh) {
            $list.Add('zh-Hant-TW')
            $zh = $list | Where-Object { $_.LanguageTag -eq 'zh-Hant-TW' } | Select-Object -First 1
        }
        if ($zh.InputMethodTips -notcontains $Tip) {
            $zh.InputMethodTips.Add($Tip)
            Set-WinUserLanguageList -LanguageList $list -Force -WarningAction SilentlyContinue
        }
        Write-Output 'keyboard list: SmartIME present'
    } else {
        if ($null -ne $zh -and $zh.InputMethodTips -contains $Tip) {
            [void]$zh.InputMethodTips.Remove($Tip)
            Set-WinUserLanguageList -LanguageList $list -Force -WarningAction SilentlyContinue
        }
        Write-Output 'keyboard list: SmartIME removed'
    }
    exit 0
} catch {
    Write-Output "ERROR: $_"
    exit 1
}
