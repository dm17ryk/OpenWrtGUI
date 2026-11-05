; Per-user installer for OpenWrtGUI (no admin rights).
; Build: ISCC.exe /DAppVersion=0.3.0 /DAppNumVersion=0.3.0.0 installer\OpenWrtGUI.iss
; tools/build_windows.ps1 and the release workflows pass both values.
; The updater runs it as: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /DIR=<app> /RELAUNCH=1

#ifndef AppVersion
  #define AppVersion "0.3.0-dev"
#endif
#ifndef AppNumVersion
  #define AppNumVersion "0.3.0.0"
#endif

[Setup]
AppId={{3F6C2B7E-9A41-4D2E-8B5C-6E1F0A9D4C27}
AppName=OpenWrtGUI
AppVersion={#AppVersion}
AppVerName=OpenWrtGUI {#AppVersion}
AppPublisher=OpenWrtGUI contributors
AppPublisherURL=https://github.com/dm17ryk/OpenWrtGUI
AppSupportURL=https://github.com/dm17ryk/OpenWrtGUI/issues
AppUpdatesURL=https://github.com/dm17ryk/OpenWrtGUI/releases
PrivilegesRequired=lowest
DefaultDirName={code:DefaultAppDir}
DisableDirPage=no
UsePreviousAppDir=yes
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=OpenWrtGUI-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
VersionInfoVersion={#AppNumVersion}
VersionInfoProductTextVersion={#AppVersion}
LicenseFile=..\LICENSE
SetupIconFile=..\packaging\openwrtgui.ico
UninstallDisplayIcon={app}\OpenWrtGUI.exe
UninstallDisplayName=OpenWrtGUI

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\OpenWrtGUI\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\OpenWrtGUI"; Filename: "{app}\OpenWrtGUI.exe"
Name: "{autodesktop}\OpenWrtGUI"; Filename: "{app}\OpenWrtGUI.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\OpenWrtGUI"; ValueType: string; ValueName: "DataDir"; ValueData: "{code:GetDataDir}"; Flags: uninsdeletekey

[Run]
Filename: "{app}\OpenWrtGUI.exe"; Description: "{cm:LaunchProgram,OpenWrtGUI}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\OpenWrtGUI.exe"; Flags: nowait; Check: ShouldRelaunch

[Code]
var
  DataDirPage: TInputDirWizardPage;
  UninstallDataDir: String;

{ Bench PCs run SentinelOne, which kills programs outside the Essence_SC tree, so when that
  tree exists the defaults go under <drive>:\Essence_SC\apps; elsewhere the usual per-user folders. }
function EssenceAppsDir: String;
begin
  if DirExists('C:\Essence_SC') then
    Result := 'C:\Essence_SC\apps'
  else if DirExists('D:\Essence_SC') then
    Result := 'D:\Essence_SC\apps'
  else
    Result := '';
end;

function DefaultAppDir(Param: String): String;
begin
  if EssenceAppsDir <> '' then
    Result := EssenceAppsDir + '\OpenWrtGUI'
  else
    Result := ExpandConstant('{localappdata}\Programs\OpenWrtGUI');
end;

function DefaultDataDir: String;
begin
  if EssenceAppsDir <> '' then
    Result := EssenceAppsDir + '\OpenWrtGUI-data'
  else
    Result := ExpandConstant('{localappdata}\OpenWrtGUI');
end;

function GetDataDir(Param: String): String;
begin
  Result := DataDirPage.Values[0];
end;

{ An existing OpenWrtGUI data folder: the app writes these two files at its top. }
function IsOwnDataDir(Dir: String): Boolean;
begin
  Result := FileExists(AddBackslash(Dir) + 'routers.json') or FileExists(AddBackslash(Dir) + 'settings.json');
end;

function IsEmptyDir(Dir: String): Boolean;
var
  Rec: TFindRec;
begin
  Result := True;
  if FindFirst(AddBackslash(Dir) + '*', Rec) then
  try
    repeat
      if (Rec.Name <> '.') and (Rec.Name <> '..') then
      begin
        Result := False;
        Exit;
      end;
    until not FindNext(Rec);
  finally
    FindClose(Rec);
  end;
end;

{ Uninstall may delete the data folder's logs, keys, audit and updates subfolders, so the data
  folder must be the app's own: new, empty, or an OpenWrtGUI data folder already. }
function DataDirProblem(Dir: String): String;
begin
  Result := '';
  Dir := RemoveBackslashUnlessRoot(Trim(Dir));
  if Dir = '' then
    Result := 'Choose a data folder.'
  else if Length(Dir) <= 3 then
    Result := 'Choose a folder of its own for the data, not the whole drive ' + Dir + '.'
  else if DirExists(Dir) and not IsEmptyDir(Dir) and not IsOwnDataDir(Dir) then
    Result := 'The data folder ' + Dir + ' already holds other files. Choose an empty or new folder ' +
              'of its own, for example ' + AddBackslash(Dir) + 'OpenWrtGUI-data.';
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Problem: String;
begin
  Result := True;
  { Silent installs run this too; PrepareToInstall refuses them without a message box. }
  if (CurPageID = DataDirPage.ID) and not WizardSilent then
  begin
    Problem := DataDirProblem(DataDirPage.Values[0]);
    if Problem <> '' then
    begin
      MsgBox(Problem, mbError, MB_OK);
      Result := False;
    end;
  end;
end;

{ Silent installs (/DATADIR=...) skip the wizard pages, so check again here; Setup then stops
  with exit code 7. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := DataDirProblem(DataDirPage.Values[0]);
end;

{ After an in-app update the silent installer starts the new version again. }
function ShouldRelaunch: Boolean;
begin
  Result := WizardSilent and (ExpandConstant('{param:RELAUNCH|0}') = '1');
end;

procedure InitializeWizard;
var
  Initial: String;
begin
  DataDirPage := CreateInputDirPage(wpSelectDir,
    'Data folder', 'Where should OpenWrtGUI keep its routers, keys and audit log?',
    'Use an empty or new folder of its own. On a PC with SentinelOne keep it inside C:\Essence_SC ' +
    'or D:\Essence_SC.' + #13#10 + 'Updates keep this folder; uninstall asks before deleting it.',
    False, '');
  DataDirPage.Add('');
  Initial := ExpandConstant('{param:DATADIR|}');
  if Initial = '' then
    Initial := GetPreviousData('DataDir', DefaultDataDir);
  DataDirPage.Values[0] := Initial;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'DataDir', DataDirPage.Values[0]);
end;

{ Deletes only what the app itself keeps there (see DataDir in src/openwrtgui/paths.py),
  then the folder if it is empty, so a data folder chosen as e.g. C:\Essence_SC stays intact. }
procedure DeleteAppData(Dir: String);
begin
  DeleteFile(Dir + '\routers.json');
  DeleteFile(Dir + '\routers.json.tmp');
  DeleteFile(Dir + '\settings.json');
  DeleteFile(Dir + '\settings.json.tmp');
  DeleteFile(Dir + '\settings.json.bad');
  DeleteFile(Dir + '\known_hosts');
  DeleteFile(Dir + '\known_hosts.tmp');
  DeleteFile(Dir + '\app.lock');
  DelTree(Dir + '\keys', True, True, True);
  DelTree(Dir + '\audit', True, True, True);
  DelTree(Dir + '\updates', True, True, True);
  DelTree(Dir + '\logs', True, True, True);
  RemoveDir(Dir);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
  begin
    { Read before [Registry] uninsdeletekey removes the value. }
    if not RegQueryStringValue(HKCU, 'Software\OpenWrtGUI', 'DataDir', UninstallDataDir) then
      UninstallDataDir := DefaultDataDir;
  end;
  { Only a folder that holds the app's own files: never a shared folder chosen some other way. }
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent and IsOwnDataDir(UninstallDataDir) then
  begin
    if MsgBox('Also delete the data folder (routers, keys, audit log)?' + #13#10#13#10 + UninstallDataDir,
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DeleteAppData(UninstallDataDir);
  end;
end;
