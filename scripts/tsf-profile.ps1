<#
.SYNOPSIS
    Add, remove or query ONE TSF language profile (input method) of an
    already-registered text service, via ITfInputProcessorProfiles.

.DESCRIPTION
    We only add our own profile under PIME's existing text service CLSID
    instead of re-running regsvr32 on PIMETextService.dll (which re-registers
    every PIME input method and failed on some machines). TSF stores profiles
    per registry view, so the installer runs this once from 64-bit and once
    from 32-bit PowerShell. Add/Remove need administrator rights; Query does not.
#>
param(
    [ValidateSet('Add', 'Remove', 'Query')][string]$Action = 'Query',
    [string]$Clsid = '{35F67E9D-A54D-4177-9697-8B0AB71A9E04}',
    [string]$Profile = '{61AA71DB-BB8C-4C7D-9BD7-C324464DF341}',
    [int]$LangId = 0x0404,
    [string]$Description = '',
    [string]$IconFile = ''
)

$ErrorActionPreference = 'Stop'

$source = @'
using System;
using System.Runtime.InteropServices;

namespace SmartIme {
    // Method order must match msctf.idl exactly (vtable layout).
    [ComImport, Guid("1F02B6C5-7842-4EE6-8A0B-9A24183A95CA"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    public interface ITfInputProcessorProfiles {
        [PreserveSig] int Register(ref Guid rclsid);
        [PreserveSig] int Unregister(ref Guid rclsid);
        [PreserveSig] int AddLanguageProfile(ref Guid rclsid, ushort langid, ref Guid guidProfile,
            [MarshalAs(UnmanagedType.LPWStr)] string pchDesc, uint cchDesc,
            [MarshalAs(UnmanagedType.LPWStr)] string pchIconFile, uint cchFile, uint uIconIndex);
        [PreserveSig] int RemoveLanguageProfile(ref Guid rclsid, ushort langid, ref Guid guidProfile);
        [PreserveSig] int EnumInputProcessorInfo(out IntPtr ppEnum);
        [PreserveSig] int GetDefaultLanguageProfile(ushort langid, ref Guid catid, out Guid pclsid, out Guid pguidProfile);
        [PreserveSig] int SetDefaultLanguageProfile(ushort langid, ref Guid rclsid, ref Guid guidProfiles);
        [PreserveSig] int ActivateLanguageProfile(ref Guid rclsid, ushort langid, ref Guid guidProfiles);
        [PreserveSig] int GetActiveLanguageProfile(ref Guid rclsid, out ushort plangid, out Guid pguidProfile);
        [PreserveSig] int GetLanguageProfileDescription(ref Guid rclsid, ushort langid, ref Guid guidProfile,
            [MarshalAs(UnmanagedType.BStr)] out string pbstrProfile);
    }

    public static class Tsf {
        static readonly Guid CLSID_TF_InputProcessorProfiles = new Guid("33C53A50-F456-4884-B049-85FD643ECFED");

        static ITfInputProcessorProfiles Create() {
            Type t = Type.GetTypeFromCLSID(CLSID_TF_InputProcessorProfiles);
            return (ITfInputProcessorProfiles)Activator.CreateInstance(t);
        }

        public static string Query(Guid clsid, ushort langid, Guid profile) {
            string desc;
            int hr = Create().GetLanguageProfileDescription(ref clsid, langid, ref profile, out desc);
            return hr == 0 ? desc : null;
        }

        public static int Add(Guid clsid, ushort langid, Guid profile, string desc, string icon) {
            return Create().AddLanguageProfile(ref clsid, langid, ref profile,
                desc, (uint)desc.Length, icon, (uint)icon.Length, 0);
        }

        public static int Remove(Guid clsid, ushort langid, Guid profile) {
            return Create().RemoveLanguageProfile(ref clsid, langid, ref profile);
        }
    }
}
'@

if (-not ('SmartIme.Tsf' -as [type])) { Add-Type -TypeDefinition $source }

$bits = 32
if ([Environment]::Is64BitProcess) { $bits = 64 }
$c = [Guid]$Clsid
$p = [Guid]$Profile

switch ($Action) {
    'Query' {
        $desc = [SmartIme.Tsf]::Query($c, [uint16]$LangId, $p)
        if ($null -eq $desc) { Write-Output "[$bits-bit] not registered" } else { Write-Output "[$bits-bit] registered: $desc" }
    }
    'Add' {
        if (-not $Description) { throw '-Description is required for Add' }
        $hr = [SmartIme.Tsf]::Add($c, [uint16]$LangId, $p, $Description, $IconFile)
        if ($hr -ne 0) { throw ("[{0}-bit] AddLanguageProfile failed: 0x{1:X8}" -f $bits, $hr) }
        Write-Output "[$bits-bit] profile added"
    }
    'Remove' {
        $hr = [SmartIme.Tsf]::Remove($c, [uint16]$LangId, $p)
        if ($hr -ne 0) { Write-Output ("[{0}-bit] RemoveLanguageProfile returned 0x{1:X8}" -f $bits, $hr) }
        else { Write-Output "[$bits-bit] profile removed" }
    }
}
