<#
.SYNOPSIS
    Cancel "delete at next restart" operations that Windows has queued for
    the given files, so files we install now are not deleted at the next boot.

.DESCRIPTION
    Uninstallers (PIME's NSIS uninstaller, or ours) cannot delete a DLL that
    applications still have loaded, so they queue the deletion in
    HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\PendingFileRenameOperations.
    If PIME is installed again before the restart, Windows would still delete
    the new PIMETextService.dll at the next boot and the input method would
    silently stop working. Entries come in pairs (source, target); a delete has
    an empty target. Only delete entries for exactly the listed paths are
    removed; everything else is written back unchanged. Needs administrator
    rights. ASCII-only (see langlist.ps1).

.PARAMETER Paths
    Full paths separated by "|" (powershell -File cannot pass an array).
#>
param([Parameter(Mandatory = $true)][string]$Paths)

$ErrorActionPreference = 'Stop'
$key = 'HKLM:\SYSTEM\CurrentControlSet\Control\Session Manager'
$name = 'PendingFileRenameOperations'
try {
    $value = (Get-ItemProperty -Path $key -Name $name -ErrorAction SilentlyContinue).$name
    if ($null -eq $value) { Write-Output 'no pending file operations'; exit 0 }
    $ops = @($value)  # a single string must not be indexed by character

    $targets = @{}
    foreach ($p in ($Paths -split '\|')) {
        if ($p) { $targets[('\??\' + $p.Trim()).ToLowerInvariant()] = $true }
    }

    $keep = New-Object System.Collections.Generic.List[string]
    $cancelled = 0
    for ($i = 0; $i -lt $ops.Count; $i += 2) {
        $src = $ops[$i]
        $dst = if ($i + 1 -lt $ops.Count) { $ops[$i + 1] } else { $null }
        # some writers prefix the source with a marker such as "*1" (Office Click-to-Run)
        $plainSrc = ($src -replace '^\*\d+', '').ToLowerInvariant()
        if ($null -ne $dst -and $dst -eq '' -and $targets.ContainsKey($plainSrc)) {
            Write-Output "cancel pending delete: $src"
            $cancelled++
            continue
        }
        $keep.Add($src)
        if ($null -ne $dst) { $keep.Add($dst) }
    }
    if ($cancelled -eq 0) { Write-Output "nothing to cancel ($($ops.Count / 2) other pending operations)"; exit 0 }
    if ($keep.Count -eq 0) {
        Remove-ItemProperty -Path $key -Name $name
    } else {
        Set-ItemProperty -Path $key -Name $name -Value ([string[]]$keep.ToArray()) -Type MultiString
    }
    Write-Output "cancelled $cancelled pending delete(s); $($keep.Count / 2) other operation(s) kept"
    exit 0
} catch {
    Write-Output "ERROR: $_"
    exit 1
}
