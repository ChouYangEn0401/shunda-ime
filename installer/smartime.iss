; Inno Setup script for 順打輸入法 (Shunda IME; code name smartime).
; Do not compile directly: tools/build_installer.py stages the files and
; prepends AppVersion, AppName, StageDir and OutputDir.
;
; What the installer does (all steps are logged; see {log}):
;   1. Install PIME silently if it is missing (bundled official setup).
;   2. Stop PIMELauncher and our backend; remove a developer junction.
;   3. Copy files to <PIME>\smartime.
;   4. Register the backend in PIME's backends.json and our TSF language
;      profile (64-bit and 32-bit registry views).
;   5. As the signed-in user: add the IME to the keyboard list, start
;      PIMELauncher, and verify that typing ji3ap7 gives 我們.

#define PimeSetupFile "PIME-1.3.0-stable-setup.exe"

[Setup]
AppId={{D0A6055C-3F02-41F7-992F-4BADAC52DDB5}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppName}
DefaultDirName={commonpf32}\PIME\smartime
DisableDirPage=yes
DisableProgramGroupPage=yes
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
cht.StepPime=正在安裝 PIME 輸入法框架…
cht.StepRegister=正在註冊輸入法…
cht.StepUser=正在加入鍵盤清單並啟動輸入法…
cht.StepVerify=正在確認輸入法可以打字…
cht.ErrPime=PIME 輸入法框架安裝失敗，請重新執行安裝程式。
cht.ErrRegister=註冊輸入法失敗（%1）。安裝紀錄：%2
cht.ErrVerify=檔案已安裝，但自動測試沒有通過：輸入法可能還沒準備好。請登出再登入後試用；如果仍然不行，請把安裝紀錄 %1 提供給開發者。
cht.Done=安裝完成，並已自動測試可以打字。%n%n按 Win + 空白鍵 切換到「{#AppName}」。系統匣圖示：自＝中英自動、中＝純中文、英＝純英文。%n%n你的設定與學到的詞存在 %%APPDATA%%\SmartIME，移除輸入法時不會刪除。
en.StepPime=Installing the PIME input method framework...
en.StepRegister=Registering the input method...
en.StepUser=Adding it to your keyboard list and starting it...
en.StepVerify=Checking that typing works...
en.ErrPime=Installing the PIME framework failed. Please run the installer again.
en.ErrRegister=Registering the input method failed (%1). Setup log: %2
en.ErrVerify=Files are installed but the automatic typing test did not pass. Sign out and in again, then try; if it still fails, send the setup log %1 to the developer.
en.Done=Installed, and a typing test passed.%n%nPress Win + Space and choose "{#AppName}". Tray icon: 自 = auto, 中 = Chinese, 英 = English.%n%nYour settings and learned words live in %%APPDATA%%\SmartIME and are kept when the input method is removed.

[Files]
Source: "{#StageDir}\smartime\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#StageDir}\{#PimeSetupFile}"; Flags: dontcopy
Source: "{#StageDir}\smartime\installer\stop-backend.ps1"; Flags: dontcopy

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

var
  InstallError: String;

function GetFileAttributes(lpFileName: String): Cardinal;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function PimeDir(): String;
begin
  Result := ExpandConstant('{commonpf32}\PIME');
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

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
  App: String;
begin
  Result := '';
  App := ExpandConstant('{app}');

  if not FileExists(PimeDir() + '\PIMELauncher.exe') then begin
    WizardForm.PreparingLabel.Caption := CustomMessage('StepPime');
    ExtractTemporaryFile('{#PimeSetupFile}');
    Log('[smartime] installing PIME');
    if (not Exec(ExpandConstant('{tmp}\{#PimeSetupFile}'), '/S', '', SW_SHOW, ewWaitUntilTerminated, Code))
       or (not FileExists(PimeDir() + '\PIMELauncher.exe')) then begin
      Result := CustomMessage('ErrPime');
      exit;
    end;
  end;

  ExtractTemporaryFile('stop-backend.ps1');
  RunLogged(PowerShell64(), PsArgs(ExpandConstant('{tmp}\stop-backend.ps1'), '-Pime "' + PimeDir() + '"'),
            'stop launcher and backend');

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

procedure CurStepChanged(CurStep: TSetupStep);
var
  App, Py, Icon, Profile: String;
  Code: Integer;
begin
  if CurStep <> ssPostInstall then
    exit;
  App := ExpandConstant('{app}');
  Py := App + '\runtime\python.exe';
  Icon := App + '\input_methods\smartime\icons\ime.ico';
  Profile := '-Action Add -Description "{#AppName}" -IconFile "' + Icon + '"';

  WizardForm.StatusLabel.Caption := CustomMessage('StepRegister');
  if RunLogged(Py, '"' + App + '\installer\pime_backends.py" add "' + PimeDir() + '"', 'backends.json') <> 0 then
    Fail('backends.json', FmtMessage(CustomMessage('ErrRegister'), ['backends.json', ExpandConstant('{log}')]));
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

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  App, Py: String;
  Code: Integer;
begin
  App := ExpandConstant('{app}');
  Py := App + '\runtime\python.exe';
  if CurUninstallStep = usUninstall then begin
    RunLogged(PowerShell64(), PsArgs(App + '\installer\stop-backend.ps1', '-Pime "' + PimeDir() + '"'), 'stop launcher and backend');
    RunLogged(PowerShell64(), PsArgs(App + '\installer\tsf-profile.ps1', '-Action Remove'), 'remove TSF profile 64-bit');
    RunLogged(PowerShell32(), PsArgs(App + '\installer\tsf-profile.ps1', '-Action Remove'), 'remove TSF profile 32-bit');
    RunLogged(Py, '"' + App + '\installer\pime_backends.py" remove "' + PimeDir() + '"', 'backends.json');
    RunLogged(PowerShell64(), PsArgs(App + '\installer\langlist.ps1', '-Action Remove'), 'keyboard list');
  end;
  if CurUninstallStep = usPostUninstall then begin
    { other PIME input methods keep working: restart the launcher as the
      desktop user (explorer.exe hands the launch to the user's shell) }
    if FileExists(PimeDir() + '\PIMELauncher.exe') then
      Exec(ExpandConstant('{win}\explorer.exe'), '"' + PimeDir() + '\PIMELauncher.exe"', '', SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;
