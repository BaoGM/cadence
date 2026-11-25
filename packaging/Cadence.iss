#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef PayloadDir
  #error PayloadDir is required
#endif
#ifndef ManifestFile
  #error ManifestFile is required
#endif
#ifndef TestBuild
  #define InstallId "Cadence.Hybrid.Studio2"
  #define RegistryBase "Software"
  #define InstallName "Cadence 2.0"
#else
  #define InstallId "Cadence.Installer.Studio2.Test"
  #define RegistryBase "Software\CadenceStudio2InstallerTests"
  #define InstallName "Cadence 2.0 Installer Test"
#endif

[Setup]
AppId={#InstallId}
AppName={#InstallName}
AppVerName={#InstallName}
AppVersion={#AppVersion}
UninstallDisplayName={#InstallName}
AppPublisher=Cadence
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\Cadence 2.0
DisableDirPage=no
DefaultGroupName=Cadence 2.0
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
#ifdef TestBuild
PrivilegesRequiredOverridesAllowed=commandline
UsePreviousPrivileges=no
#else
PrivilegesRequiredOverridesAllowed=dialog
#endif
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
UsePreviousAppDir=yes
UsePreviousTasks=yes
WizardStyle=modern dynamic
SetupIconFile=..\assets\cadence.ico
UninstallDisplayIcon={app}\Cadence.exe
UninstallFilesDir={app}\uninstall
OutputBaseFilename=Cadence-{#AppVersion}-Setup
#ifdef TestBuild
Compression=none
SolidCompression=no
#else
Compression=lzma2/normal
SolidCompression=yes
#endif
LZMANumBlockThreads=1
CloseApplications=yes
CloseApplicationsFilter=Cadence.exe
RestartApplications=no
ChangesAssociations=yes
SetupLogging=yes
UninstallLogging=yes

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
french.DesktopShortcut=Créer un raccourci sur le bureau
english.DesktopShortcut=Create a desktop shortcut
french.FileRegistration=Proposer Cadence dans « Ouvrir avec »
english.FileRegistration=Offer Cadence in Open with
french.LaunchCadence=Lancer Cadence
english.LaunchCadence=Launch Cadence
french.DefaultApps=Choisir les applications par défaut de Windows
english.DefaultApps=Choose Windows default apps
french.SeparateDirectory=Ce dossier contient déjà une autre version de Cadence. Choisissez un dossier réservé à Cadence 2.0.
english.SeparateDirectory=This folder already contains another version of Cadence. Choose a separate folder for Cadence 2.0.
french.MaintenanceFailure=Windows n’a pas pu configurer les mises à jour de cette installation. Consultez le journal d’installation.
english.MaintenanceFailure=Windows could not configure updates for this installation. See the installation log.

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked
Name: "filetypes"; Description: "{cm:FileRegistration}"; Flags: unchecked

[Files]
#ifdef MaintenanceDir
Source: "{#MaintenanceDir}\CadenceMaintenanceSetup.exe"; DestDir: "{commonpf64}\Cadence Studio Maintenance"; Flags: ignoreversion; Check: MachineMaintenance
Source: "{#MaintenanceDir}\CadenceMaintenance.exe"; DestDir: "{commonpf64}\Cadence Studio Maintenance"; Flags: ignoreversion; Check: MachineMaintenance
Source: "{#MaintenanceDir}\CadenceRestart.exe"; DestDir: "{commonpf64}\Cadence Studio Maintenance"; Flags: ignoreversion; Check: MachineMaintenance
#endif
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ManifestFile}"; DestDir: "{app}\uninstall"; DestName: "installed-files.txt"; Flags: ignoreversion

[Icons]
#ifndef TestBuild
Name: "{autoprograms}\Cadence 2.0"; Filename: "{app}\Cadence.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Cadence 2.0"; Filename: "{app}\Cadence.exe"; WorkingDir: "{app}"; Tasks: desktopicon
#else
Name: "{app}\Test Start Menu\Cadence"; Filename: "{app}\Cadence.exe"; WorkingDir: "{app}"
#endif

[UninstallDelete]
Type: filesandordirs; Name: "{app}\.cadence-updates"; Check: not IsAdminInstallMode and FileExists(ExpandConstant('{app}\.cadence-updates\state.json'))

[Registry]
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Studio2.Installed.Project"; ValueType: string; ValueData: "Cadence Project"; Flags: uninsdeletekey; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Studio2.Installed.Project\DefaultIcon"; ValueType: string; ValueData: """{app}\Cadence.exe"",0"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Studio2.Installed.Project\shell\open\command"; ValueType: string; ValueData: """{app}\Cadence.exe"" ""%1"""; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Studio2.Installed.Media"; ValueType: string; ValueData: "Cadence Media"; Flags: uninsdeletekey; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Studio2.Installed.Media\DefaultIcon"; ValueType: string; ValueData: """{app}\Cadence.exe"",0"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Studio2.Installed.Media\shell\open\command"; ValueType: string; ValueData: """{app}\Cadence.exe"" ""%1"""; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\CadenceStudio2\InstalledCapabilities"; ValueName: "ApplicationName"; ValueType: string; ValueData: "Cadence 2.0"; Flags: uninsdeletekey; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\CadenceStudio2\InstalledCapabilities"; ValueName: "ApplicationDescription"; ValueType: string; ValueData: "Cadence video player and editor"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\CadenceStudio2\InstalledCapabilities"; ValueName: "ApplicationIcon"; ValueType: string; ValueData: """{app}\Cadence.exe"",0"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\RegisteredApplications"; ValueName: "Cadence.Studio2.Installed"; ValueType: string; ValueData: "{#RegistryBase}\CadenceStudio2\InstalledCapabilities"; Flags: uninsdeletevalue; Tasks: filetypes
#include AssociationsFile

[Run]
Filename: "{app}\Cadence.exe"; Description: "{cm:LaunchCadence}"; Flags: postinstall unchecked nowait skipifsilent
Filename: "ms-settings:defaultapps"; Description: "{cm:DefaultApps}"; Flags: postinstall unchecked shellexec nowait skipifsilent; Tasks: filetypes

[Code]
var
  PreviousFiles: TArrayOfString;
#ifdef MaintenanceDir
  MaintenancePrepared: Boolean;

function MachineMaintenance: Boolean;
begin
  Result := IsAdminInstallMode and
    (CompareText(RemoveBackslashUnlessRoot(ExpandConstant('{app}')), ExpandConstant('{commonpf64}\Cadence 2.0')) = 0);
end;

function MaintenanceCommand(const ProgramPath, Action: String): Boolean;
var
  Code: Integer;
begin
  Result := Exec(ProgramPath, Action, ExtractFileDir(ProgramPath), SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
  Log(Format('Cadence maintenance %s: %d', [Action, Code]));
end;
#endif

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ExistingExe, ExistingVersion: String;
begin
  Result := '';
  ExistingExe := ExpandConstant('{app}\Cadence.exe');
  if FileExists(ExistingExe) then
    if not GetVersionNumbersString(ExistingExe, ExistingVersion) or (Pos('2.', ExistingVersion) <> 1) then
      Result := CustomMessage('SeparateDirectory');
#ifdef MaintenanceDir
  if (Result = '') and MachineMaintenance then begin
    ExtractTemporaryFile('CadenceMaintenanceSetup.exe');
    if MaintenanceCommand(ExpandConstant('{tmp}\CadenceMaintenanceSetup.exe'), 'prepare') then
      MaintenancePrepared := True
    else Result := CustomMessage('MaintenanceFailure');
  end;
#endif
end;

function UpdateFileAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function ManagedRuntimePath(RelativeName: String): Boolean;
var
  LowerName, Component, Parent: String;
  I, Dots: Integer;
begin
  Result := False;
  LowerName := Lowercase(RelativeName);
  if (Pos('..', LowerName) > 0) or (Pos(':', LowerName) > 0) or (Pos('/', LowerName) > 0) then Exit;
  Component := Copy(LowerName, 1, Pos('\', LowerName) - 1);
  if (Component <> '_internal') and (Component <> 'licences') then begin
    if Pos('_internal-', Component) <> 1 then Exit;
    Component := Copy(Component, 11, MaxInt);
    Dots := 0;
    for I := 1 to Length(Component) do begin
      if Component[I] = '.' then begin
        Dots := Dots + 1;
        if (I = 1) or (I = Length(Component)) then Exit;
      end else if (Component[I] < '0') or (Component[I] > '9') then Exit;
    end;
    if Dots <> 2 then Exit;
  end;
  Parent := ExpandConstant('{app}\') + RelativeName;
  while CompareText(Parent, ExpandConstant('{app}')) <> 0 do begin
    if (UpdateFileAttributes(Parent) and $400) <> 0 then Exit;
    Parent := ExtractFileDir(Parent);
    if Length(Parent) < Length(ExpandConstant('{app}')) then Exit;
  end;
  Result := True;
end;

procedure RemoveObsoleteFiles(Uninstalling: Boolean);
var
  CurrentFiles: TArrayOfString;
  I, J: Integer;
  RelativeName, Target, Digest, Parent: String;
  StillInstalled: Boolean;
begin
  if IsAdminInstallMode then Exit;
  if not Uninstalling then
    if not LoadStringsFromFile(ExpandConstant('{app}\uninstall\installed-files.txt'), CurrentFiles) then Exit;
  for I := 0 to GetArrayLength(PreviousFiles) - 1 do begin
    if (Length(PreviousFiles[I]) < 66) or (Copy(PreviousFiles[I], 65, 1) <> '|') then Continue;
    Digest := Copy(PreviousFiles[I], 1, 64);
    RelativeName := Copy(PreviousFiles[I], 66, MaxInt);
    if not ManagedRuntimePath(RelativeName) then Continue;
    StillInstalled := False;
    for J := 0 to GetArrayLength(CurrentFiles) - 1 do
      if CompareText(Copy(CurrentFiles[J], 66, MaxInt), RelativeName) = 0 then begin
        StillInstalled := True;
        Break;
      end;
    if StillInstalled then Continue;
    Target := ExpandConstant('{app}\') + RelativeName;
    if not FileExists(Target) then Continue;
    try
      if CompareText(GetSHA256OfFile(Target), Digest) = 0 then begin
        if DeleteFile(Target) then begin
          Parent := ExtractFileDir(Target);
          while CompareText(Parent, ExpandConstant('{app}')) <> 0 do begin
            if not RemoveDir(Parent) then Break;
            Parent := ExtractFileDir(Parent);
          end;
        end;
      end else Log('Preserved modified file: ' + RelativeName);
    except
      Log('Could not inspect obsolete file: ' + RelativeName);
    end;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssInstall then
    LoadStringsFromFile(ExpandConstant('{app}\uninstall\installed-files.txt'), PreviousFiles);
  if CurStep = ssPostInstall then begin
    RemoveObsoleteFiles(False);
#ifdef MaintenanceDir
    if MachineMaintenance then begin
      if not MaintenanceCommand(ExpandConstant('{commonpf64}\Cadence Studio Maintenance\CadenceMaintenanceSetup.exe'), 'install') then
        RaiseException(CustomMessage('MaintenanceFailure'));
      MaintenancePrepared := False;
    end;
#endif
  end;
end;

#ifdef MaintenanceDir
procedure DeinitializeSetup();
var
  Code: Integer;
begin
  if MaintenancePrepared then
    Exec(ExpandConstant('{sys}\sc.exe'), 'start CadenceStudio2Maintenance', '', SW_HIDE, ewWaitUntilTerminated, Code);
end;
#endif

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
#ifdef MaintenanceDir
  if (CurUninstallStep = usUninstall) and MachineMaintenance then
    if not MaintenanceCommand(ExpandConstant('{commonpf64}\Cadence Studio Maintenance\CadenceMaintenanceSetup.exe'), 'remove') then
      RaiseException(CustomMessage('MaintenanceFailure'));
#endif
  if (CurUninstallStep = usUninstall) and not IsAdminInstallMode then
    if LoadStringsFromFile(ExpandConstant('{app}\uninstall\installed-files.txt'), PreviousFiles) then RemoveObsoleteFiles(True);
end;
