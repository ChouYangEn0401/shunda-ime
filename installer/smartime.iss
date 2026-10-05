; Inno Setup script for 順打輸入法 (Shunda IME; code name smartime).
; Do not compile directly: tools/build_installer.py stages the files and
; prepends AppVersion, AppName, StageDir, OutputDir and the SHA-256 of the
; three PIME core files (ShaLauncher, ShaDll64, ShaDll86).
;
; PIME is the input method framework we run on (a TSF text service DLL that
; apps load, plus PIMELauncher.exe that starts our Python backend). PIME's
; official setup also installs its own input methods (Chewing and others),
; so we never run it. Two cases:
;
;   * "core" mode - PIME is not installed (or was installed by us): we put
;     only the PIME core files into C:\Program Files (x86)\PIME (unmodified,
;     taken from the official PIME 1.3.0 release), list only our backend in
;     backends.json and register the DLLs with regsvr32, like PIME's own
;     installer does. Only 順打輸入法 appears in the keyboard list.
;   * "shared" mode - the official PIME is installed (its other input methods
;     may be in use): we only add our backend and our TSF profile. The user
;     may tick a task to remove PIME's other input methods; then we switch the
;     install to core mode in place.
;
; Steps (all logged; see {log}):
;   1. Stop PIMELauncher and our backend; remove a developer junction.
;   2. Copy files (core files only when missing or different).
;   3. Register: backends.json, PIME DLLs (core mode), our TSF profile in the
;      64-bit and 32-bit registry views, PIMELauncher at sign-in (core mode).
;   4. As the signed-in user: add the IME to the keyboard list, start
;      PIMELauncher, and verify that typing ji3ap7 gives 我們.

[Setup]
AppId={{D0A6055C-3F02-41F7-992F-4BADAC52DDB5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={commonpf32}\PIME\smartime
DisableDirPage=yes
DisableProgramGroupPage=yes
; the "takeover" task must be a fresh choice every time
UsePreviousTasks=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=ShundaIME-Setup-{#AppVersion}
SetupIconFile={#StageDir}\smartime\input_methods\smartime\icons\ime.ico
UninstallDisplayIcon={app}\input_methods\smartime\icons\ime.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
CloseApplications=no
ShowLanguageDialog=no
LanguageDetectionMethod=uilanguage

[Languages]
Name: "cht"; MessagesFile: "{#StageDir}\ChineseTraditional.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
cht.OpenSettings=開啟「{#AppName} 設定」
en.OpenSettings=Open {#AppName} settings
cht.TaskGroup=這台電腦已經裝了 PIME 官方版（含新酷音等輸入法）。順打輸入法會和它共用 PIME。
cht.TaskTakeover=移除 PIME 官方版附帶的其他輸入法（新酷音等），只保留順打輸入法
cht.StepPrepare=正在停止輸入法背景程式…
cht.StepTakeover=正在移除 PIME 官方版附帶的其他輸入法…
cht.StepRegister=正在註冊輸入法…
cht.StepUser=正在加入鍵盤清單並啟動輸入法…
cht.StepVerify=正在確認輸入法可以打字…
cht.ErrRegister=註冊輸入法失敗（%1）。安裝紀錄：%2
cht.ErrVerify=檔案已安裝，但自動測試沒有通過：輸入法可能還沒準備好。請登出再登入後試用；如果仍然不行，請把安裝紀錄 %1 提供給開發者。
cht.Done=安裝完成，並已自動測試可以打字。%n%n按 Win + 空白鍵 切換到「{#AppName}」。系統匣圖示：自＝中英自動、中＝純中文、英＝純英文。%n%n你的設定與學到的詞存在 %%APPDATA%%\SmartIME，移除輸入法時不會刪除。
en.TaskGroup=The official PIME (with Chewing and other input methods) is installed. Shunda IME shares PIME with it.
en.TaskTakeover=Remove the other input methods that came with the official PIME (Chewing etc.) and keep only Shunda IME
en.StepPrepare=Stopping the input method background programs...
en.StepTakeover=Removing the other input methods of the official PIME...
en.StepRegister=Registering the input method...
en.StepUser=Adding it to your keyboard list and starting it...
en.StepVerify=Checking that typing works...
en.ErrRegister=Registering the input method failed (%1). Setup log: %2
en.ErrVerify=Files are installed but the automatic typing test did not pass. Sign out and in again, then try; if it still fails, send the setup log %1 to the developer.
en.Done=Installed, and a typing test passed.%n%nPress Win + Space and choose "{#AppName}". Tray icon: 自 = auto, 中 = Chinese, 英 = English.%n%nYour settings and learned words live in %%APPDATA%%\SmartIME and are kept when the input method is removed.

[Tasks]
Name: "takeover"; Description: "{cm:TaskTakeover}"; GroupDescription: "{cm:TaskGroup}"; Check: OfficialPimeInstalled; Flags: unchecked

[Files]
Source: "{#StageDir}\smartime\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; PIME core (core mode only). Removed by our own uninstall code, not by the
; uninstall log, because an identical file already in place is not copied.
Source: "{#StageDir}\pime\PIMELauncher.exe"; DestDir: "{commonpf32}\PIME"; Flags: ignoreversion uninsneveruninstall; Check: NeedCoreFile('PIMELauncher.exe', '{#ShaLauncher}')
Source: "{#StageDir}\pime\x64\PIMETextService.dll"; DestDir: "{commonpf32}\PIME\x64"; Flags: ignoreversion uninsneveruninstall; Check: NeedCoreFile('x64\PIMETextService.dll', '{#ShaDll64}')
Source: "{#StageDir}\pime\x86\PIMETextService.dll"; DestDir: "{commonpf32}\PIME\x86"; Flags: ignoreversion uninsneveruninstall; Check: NeedCoreFile('x86\PIMETextService.dll', '{#ShaDll86}')
Source: "{#StageDir}\smartime\installer\stop-backend.ps1"; Flags: dontcopy
Source: "{#StageDir}\smartime\installer\pending-deletes.ps1"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\{#AppName} 設定"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\settings.py"""; WorkingDir: "{app}"; IconFilename: "{app}\input_methods\smartime\icons\ime.ico"

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\settings.py"""; WorkingDir: "{app}"; Description: "{cm:OpenSettings}"; Flags: postinstall nowait skipifsilent runasoriginaluser unchecked

[UninstallDelete]
; Python creates __pycache__ folders at run time; remove the whole folder.
Type: filesandordirs; Name: "{app}"

[Code]
const
  { FILE_ATTRIBUTE_REPARSE_POINT is predefined by Inno Setup }
  NO_FILE_ATTRIBUTES = $FFFFFFFF;
  MOVEFILE_DELAY_UNTIL_REBOOT = 4;
  OfficialPimeKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\PIME';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

var
  InstallError: String;
  CoreMode: Boolean;   { we provide the PIME core (see the top of this file) }
  Takeover: Boolean;   { official PIME present and the user chose to keep only us }

function GetFileAttributes(lpFileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

{ lpNewFileName = NULL (0) with MOVEFILE_DELAY_UNTIL_REBOOT: delete at the next restart }
function MoveFileExDelete(lpExistingFileName: String; lpNewFileName: Cardinal; dwFlags: Cardinal): Boolean;
  external 'MoveFileExW@kernel32.dll stdcall';

function PimeDir(): String;
begin
  Result := ExpandConstant('{commonpf32}\PIME');
end;

{ The official PIME setup writes its uninstall entry to the 64-bit registry view. }
function OfficialPimeInstalled(): Boolean;
begin
  Result := RegKeyExists(HKLM64, OfficialPimeKey);
end;

// 64-bit install mode: the {sys} constant is the real System32 for Exec (and
// for the 64-bit cmd.exe that RunLogged uses, which cannot see "Sysnative").
function PowerShell64(): String;
begin
  Result := ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe');
end;

{ For ExecAsOriginalUser, which starts the program from the non-elevated
  Setup process: let Windows pick PowerShell from the PATH. }
function UserPowerShell(): String;
begin
  Result := 'powershell.exe';
end;

function PowerShell32(): String;
begin
  Result := ExpandConstant('{syswow64}\WindowsPowerShell\v1.0\powershell.exe');
end;

function Regsvr64(): String;
begin
  Result := ExpandConstant('{sys}\regsvr32.exe');
end;

function Regsvr32(): String;
begin
  Result := ExpandConstant('{syswow64}\regsvr32.exe');
end;

function PsArgs(const Script, Params: String): String;
begin
  Result := '-NoProfile -ExecutionPolicy Bypass -File "' + Script + '" ' + Params;
end;

{ Run a program hidden, wait, and copy its output into the setup log. }
function RunLogged(const Exe, Params, What: String): Integer;
var
  OutFile: String;
  Output: AnsiString;
  Code: Integer;
begin
  OutFile := ExpandConstant('{tmp}\step-output.txt');
  DeleteFile(OutFile);
  Log('[smartime] ' + What + ': ' + Exe + ' ' + Params);
  if not Exec(ExpandConstant('{cmd}'), '/C ""' + Exe + '" ' + Params + ' > "' + OutFile + '" 2>&1"', '',
              SW_HIDE, ewWaitUntilTerminated, Code) then
    Code := -1;
  if LoadStringFromFile(OutFile, Output) then
    Log('[smartime] ' + What + ' output: ' + String(Output));
  Log('[smartime] ' + What + ' exit code ' + IntToStr(Code));
  Result := Code;
end;

{ Same, but as the user who started Setup (per-user settings, PIMELauncher). }
function RunAsUser(const Exe, Params, What: String; Wait: Boolean): Integer;
var
  Code: Integer;
  WaitMode: TExecWait;
begin
  if Wait then WaitMode := ewWaitUntilTerminated else WaitMode := ewNoWait;
  Log('[smartime] ' + What + ' (as user): ' + Exe + ' ' + Params);
  if not ExecAsOriginalUser(Exe, Params, '', SW_HIDE, WaitMode, Code) then
    Code := -1;
  Log('[smartime] ' + What + ' exit code ' + IntToStr(Code));
  Result := Code;
end;

function IsJunction(const Path: String): Boolean;
var
  Attr: Cardinal;
begin
  Attr := GetFileAttributes(Path);
  Result := (Attr <> NO_FILE_ATTRIBUTES) and ((Attr and FILE_ATTRIBUTE_REPARSE_POINT) <> 0);
end;

function SameSha(const Path, Sha: String): Boolean;
begin
  try
    Result := CompareText(GetSHA256OfFile(Path), Sha) = 0;
  except
    Result := False;
  end;
end;

{ [Files] check: copy a PIME core file only in core mode, and only when it is
  missing or different (an identical DLL may be loaded by running apps). }
function NeedCoreFile(const Rel, Sha: String): Boolean;
var
  Path: String;
begin
  Path := PimeDir() + '\' + Rel;
  Result := CoreMode and not (FileExists(Path) and SameSha(Path, Sha));
  Log('[smartime] core file ' + Rel + ': ' + Format('%d', [Ord(Result)]) + ' (1 = copy)');
end;

{ Get a file out of the way. A DLL that apps still have loaded cannot be
  deleted, but it can be renamed; the renamed copy is deleted at the next
  restart, so the real path is free right away and nothing is queued for it. }
procedure RemoveOrRename(const Path: String);
var
  Old: String;
begin
  if not FileExists(Path) then
    exit;
  if DeleteFile(Path) then begin
    Log('[smartime] deleted ' + Path);
    exit;
  end;
  Old := Path + '.' + GetDateTimeString('yyyymmddhhnnss', #0, #0) + '.old';
  if RenameFile(Path, Old) then begin
    MoveFileExDelete(Old, 0, MOVEFILE_DELAY_UNTIL_REBOOT);
    Log('[smartime] in use, renamed to ' + Old + ' (deleted at the next restart)');
  end else
    Log('[smartime] could not remove ' + Path);
end;

{ Remove a folder now if it is empty, else when Windows restarts (only if it
  is empty by then, so an install before the restart is not affected). }
procedure RemoveDirSoon(const Dir: String);
begin
  if DirExists(Dir) and not RemoveDir(Dir) then
    MoveFileExDelete(Dir, 0, MOVEFILE_DELAY_UNTIL_REBOOT);
end;

procedure PrepareCoreFile(const Rel, Sha: String);
var
  Path: String;
begin
  Path := PimeDir() + '\' + Rel;
  if FileExists(Path) and not SameSha(Path, Sha) then
    RemoveOrRename(Path);
end;

{ Turn an official PIME install into a core install: its own input methods
  (python\, node\), uninstaller and Start menu folder go; the launcher and
  DLLs are the same files we would install, so they stay. }
procedure RemoveOfficialPimeExtras();
var
  Name: String;
begin
  Log('[smartime] takeover: removing the official PIME input methods');
  if not RegQueryStringValue(HKLM64, OfficialPimeKey, 'DisplayName', Name) then
    Name := 'PIME';
  DelTree(PimeDir() + '\python', True, True, True);
  DelTree(PimeDir() + '\node', True, True, True);
  DeleteFile(PimeDir() + '\Uninstall.exe');
  DeleteFile(PimeDir() + '\version.txt');
  if Name <> '' then begin
    DelTree(ExpandConstant('{userprograms}\') + Name, True, True, True);
    DelTree(ExpandConstant('{commonprograms}\') + Name, True, True, True);
  end;
  RegDeleteKeyIncludingSubkeys(HKLM64, OfficialPimeKey);
  RegDeleteKeyIncludingSubkeys(HKLM64, 'Software\PIME');
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  App, Pime: String;
begin
  Result := '';
  App := ExpandConstant('{app}');
  Pime := PimeDir();
  Takeover := OfficialPimeInstalled() and WizardIsTaskSelected('takeover');
  CoreMode := Takeover or not OfficialPimeInstalled();
  Log('[smartime] mode: ' + Format('core=%d takeover=%d', [Ord(CoreMode), Ord(Takeover)]));

  WizardForm.PreparingLabel.Caption := CustomMessage('StepPrepare');
  ExtractTemporaryFile('stop-backend.ps1');
  RunLogged(PowerShell64(), PsArgs(ExpandConstant('{tmp}\stop-backend.ps1'), '-Pime "' + Pime + '"'),
            'stop launcher and backend');

  if Takeover then begin
    WizardForm.PreparingLabel.Caption := CustomMessage('StepTakeover');
    RemoveOfficialPimeExtras();
  end;

  if CoreMode then begin
    { files we are about to install must not be deleted at the next restart
      (queued by an uninstall that ran while apps had the DLL loaded) }
    ExtractTemporaryFile('pending-deletes.ps1');
    RunLogged(PowerShell64(), PsArgs(ExpandConstant('{tmp}\pending-deletes.ps1'),
              '-Paths "' + Pime + '\PIMELauncher.exe|' + Pime + '\x64\PIMETextService.dll|' +
              Pime + '\x86\PIMETextService.dll"'), 'cancel pending deletes');
    PrepareCoreFile('PIMELauncher.exe', '{#ShaLauncher}');
    PrepareCoreFile('x64\PIMETextService.dll', '{#ShaDll64}');
    PrepareCoreFile('x86\PIMETextService.dll', '{#ShaDll86}');
  end;

  if IsJunction(App) then
    { developer install (install.ps1 -Dev): remove the link only, never its target }
    RunLogged(ExpandConstant('{cmd}'), '/C rmdir "' + App + '"', 'remove developer junction')
  else if DirExists(App + '\app\src') then
    { upgrade: drop old sources so removed modules do not linger }
    DelTree(App + '\app\src', True, True, True);
end;

procedure Fail(const Step, Msg: String);
begin
  if InstallError = '' then
    InstallError := Msg;
  Log('[smartime] ERROR at ' + Step + ': ' + Msg);
end;

procedure RegisterCore();
var
  Dll64, Dll86: String;
begin
  Dll64 := '"' + PimeDir() + '\x64\PIMETextService.dll"';
  Dll86 := '"' + PimeDir() + '\x86\PIMETextService.dll"';
  if Takeover then begin
    { drop the profiles of PIME's other input methods; registered again below
      with a backends.json that lists only ours }
    RunLogged(Regsvr64(), '/u /s ' + Dll64, 'unregister PIME 64-bit');
    RunLogged(Regsvr32(), '/u /s ' + Dll86, 'unregister PIME 32-bit');
  end;
  { PIMETextService.dll registers the COM class, the TSF categories and one
    language profile per ime.json of every backend in backends.json }
  if RunLogged(Regsvr64(), '/s ' + Dll64, 'register PIME 64-bit') <> 0 then
    Fail('regsvr64', FmtMessage(CustomMessage('ErrRegister'), ['PIMETextService 64-bit', ExpandConstant('{log}')]));
  if RunLogged(Regsvr32(), '/s ' + Dll86, 'register PIME 32-bit') <> 0 then
    Fail('regsvr32', FmtMessage(CustomMessage('ErrRegister'), ['PIMETextService 32-bit', ExpandConstant('{log}')]));
  { start the launcher at every sign-in (what PIME's own installer does) }
  if not RegWriteStringValue(HKLM64, RunKey, 'PIMELauncher', PimeDir() + '\PIMELauncher.exe') then
    Fail('autostart', FmtMessage(CustomMessage('ErrRegister'), ['PIMELauncher autostart', ExpandConstant('{log}')]));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  App, Py, Icon, Profile, Backends: String;
  Code: Integer;
begin
  if CurStep <> ssPostInstall then
    exit;
  App := ExpandConstant('{app}');
  Py := App + '\runtime\python.exe';
  Icon := App + '\input_methods\smartime\icons\ime.ico';
  Profile := '-Action Add -Description "{#AppName}" -IconFile "' + Icon + '"';

  WizardForm.StatusLabel.Caption := CustomMessage('StepRegister');
  { compile the engine once now: users cannot write __pycache__ under
    Program Files, so otherwise every backend start compiles it again }
  RunLogged(Py, '-m compileall -q "' + App + '\app\src"', 'precompile');

  if CoreMode then Backends := 'only' else Backends := 'add';
  if RunLogged(Py, '"' + App + '\installer\pime_backends.py" ' + Backends + ' "' + PimeDir() + '"', 'backends.json') <> 0 then
    Fail('backends.json', FmtMessage(CustomMessage('ErrRegister'), ['backends.json', ExpandConstant('{log}')]));
  if CoreMode then
    RegisterCore();
  if RunLogged(PowerShell64(), PsArgs(App + '\installer\tsf-profile.ps1', Profile), 'TSF profile 64-bit') <> 0 then
    Fail('tsf64', FmtMessage(CustomMessage('ErrRegister'), ['TSF 64-bit', ExpandConstant('{log}')]));
  if RunLogged(PowerShell32(), PsArgs(App + '\installer\tsf-profile.ps1', Profile), 'TSF profile 32-bit') <> 0 then
    Fail('tsf32', FmtMessage(CustomMessage('ErrRegister'), ['TSF 32-bit', ExpandConstant('{log}')]));

  WizardForm.StatusLabel.Caption := CustomMessage('StepUser');
  RunAsUser(UserPowerShell(), PsArgs(App + '\installer\langlist.ps1', '-Action Add'), 'keyboard list', True);
  { explorer.exe hands the launch to the desktop shell, so the launcher (and
    our backend) run with the user's normal rights even when Setup itself
    was started with "Run as administrator" }
  Log('[smartime] start PIMELauncher via explorer.exe');
  Exec(ExpandConstant('{win}\explorer.exe'), '"' + PimeDir() + '\PIMELauncher.exe"', '', SW_SHOWNORMAL, ewNoWait, Code);
  Sleep(1500);

  WizardForm.StatusLabel.Caption := CustomMessage('StepVerify');
  Sleep(1500);
  if RunAsUser(Py, '"' + App + '\installer\verify.py"', 'verify typing', True) <> 0 then
    Fail('verify', FmtMessage(CustomMessage('ErrVerify'), [ExpandConstant('{log}')]));

  if InstallError <> '' then
    SuppressibleMsgBox(InstallError, mbError, MB_OK, IDOK)
  else
    Log('[smartime] install verified');
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpFinished then begin
    if InstallError = '' then
      WizardForm.FinishedLabel.Caption := CustomMessage('Done')
    else
      WizardForm.FinishedLabel.Caption := InstallError;
  end;
end;

procedure RemoveCore();
var
  Pime, Launcher, Value: String;
begin
  Pime := PimeDir();
  Launcher := Pime + '\PIMELauncher.exe';
  if RegQueryStringValue(HKLM64, RunKey, 'PIMELauncher', Value) and (CompareText(Value, Launcher) = 0) then
    RegDeleteValue(HKLM64, RunKey, 'PIMELauncher');
  RemoveOrRename(Launcher);
  RemoveOrRename(Pime + '\x64\PIMETextService.dll');
  RemoveOrRename(Pime + '\x86\PIMETextService.dll');
  DeleteFile(Pime + '\backends.json');
  DeleteFile(Pime + '\backends.json.smartime-backup');
  RemoveDirSoon(Pime + '\x64');
  RemoveDirSoon(Pime + '\x86');
  RemoveDirSoon(Pime);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App, Py: String;
  Code: Integer;
begin
  App := ExpandConstant('{app}');
  Py := App + '\runtime\python.exe';
  if CurUninstallStep = usUninstall then begin
    { no official PIME: the PIME core in Program Files is ours, remove it too }
    CoreMode := not OfficialPimeInstalled();
    Log('[smartime] uninstall, core mode: ' + Format('%d', [Ord(CoreMode)]));
    RunLogged(PowerShell64(), PsArgs(App + '\installer\stop-backend.ps1', '-Pime "' + PimeDir() + '"'), 'stop launcher and backend');
    if CoreMode then begin
      RunLogged(Regsvr64(), '/u /s "' + PimeDir() + '\x64\PIMETextService.dll"', 'unregister PIME 64-bit');
      RunLogged(Regsvr32(), '/u /s "' + PimeDir() + '\x86\PIMETextService.dll"', 'unregister PIME 32-bit');
    end;
    RunLogged(PowerShell64(), PsArgs(App + '\installer\tsf-profile.ps1', '-Action Remove'), 'remove TSF profile 64-bit');
    RunLogged(PowerShell32(), PsArgs(App + '\installer\tsf-profile.ps1', '-Action Remove'), 'remove TSF profile 32-bit');
    if not CoreMode then
      RunLogged(Py, '"' + App + '\installer\pime_backends.py" remove "' + PimeDir() + '"', 'backends.json');
    RunLogged(PowerShell64(), PsArgs(App + '\installer\langlist.ps1', '-Action Remove'), 'keyboard list');
  end;
  if CurUninstallStep = usPostUninstall then begin
    if CoreMode then
      RemoveCore()
    else if FileExists(PimeDir() + '\PIMELauncher.exe') then
      { other PIME input methods keep working: restart the launcher as the
        desktop user (explorer.exe hands the launch to the user's shell) }
      Exec(ExpandConstant('{win}\explorer.exe'), '"' + PimeDir() + '\PIMELauncher.exe"', '', SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;
