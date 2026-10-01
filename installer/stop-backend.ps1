<#
.SYNOPSIS
    Stop PIMELauncher and any SmartIME backend process so files can be
    replaced or removed. ASCII-only (see langlist.ps1).
#>
param([Parameter(Mandatory = $true)][string]$Pime)

$launcher = Join-Path $Pime 'PIMELauncher.exe'
if (Test-Path $launcher) {
    # Ask the running launcher to quit; it also stops its backends.
    Start-Process -FilePath $launcher -ArgumentList '/quit' -Wait -ErrorAction SilentlyContinue
}
$deadline = (Get-Date).AddSeconds(5)
while ((Get-Process PIMELauncher -ErrorAction SilentlyContinue) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 200
}
Get-Process PIMELauncher -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

# Our backend runs from <PIME>\smartime\runtime\python.exe, the settings
# window from pythonw.exe there; both keep the system lexicon open.
$runtime = Join-Path $Pime 'smartime\runtime'
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.ExecutablePath -and ((Split-Path $_.ExecutablePath -Parent) -ieq $runtime) } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300
exit 0
