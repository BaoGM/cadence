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
  #define InstallId "Cadence.Hybrid"
  #define RegistryBase "Software"
  #define InstallName "Cadence"
#else
  #define InstallId "Cadence.Installer.Test"
  #define RegistryBase "Software\CadenceInstallerTests"
  #define InstallName "Cadence Installer Test"
#endif

[Setup]
AppId={#InstallId}
AppName={#InstallName}
AppVerName={#InstallName}
AppVersion={#AppVersion}
UninstallDisplayName={#InstallName}
AppPublisher=Cadence
VersionInfoVersion={#AppVersion}.0
DefaultDirName={autopf}\Cadence
DisableDirPage=no
DefaultGroupName=Cadence
DisableProgramGroupPage=yes
PrivilegesRequired=admin
#ifdef TestBuild
PrivilegesRequiredOverridesAllowed=commandline
UsePreviousPrivileges=no
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
Compression=lzma2/normal
SolidCompression=yes
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

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked
Name: "filetypes"; Description: "{cm:FileRegistration}"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ManifestFile}"; DestDir: "{app}\uninstall"; DestName: "installed-files.txt"; Flags: ignoreversion

[Icons]
#ifndef TestBuild
Name: "{autoprograms}\Cadence"; Filename: "{app}\Cadence.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\Cadence"; Filename: "{app}\Cadence.exe"; WorkingDir: "{app}"; Tasks: desktopicon
#else
Name: "{app}\Test Start Menu\Cadence"; Filename: "{app}\Cadence.exe"; WorkingDir: "{app}"
#endif

[Registry]
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Installed.Project"; ValueType: string; ValueData: "Cadence Project"; Flags: uninsdeletekey; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Installed.Project\DefaultIcon"; ValueType: string; ValueData: """{app}\Cadence.exe"",0"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Installed.Project\shell\open\command"; ValueType: string; ValueData: """{app}\Cadence.exe"" ""%1"""; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Installed.Media"; ValueType: string; ValueData: "Cadence Media"; Flags: uninsdeletekey; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Installed.Media\DefaultIcon"; ValueType: string; ValueData: """{app}\Cadence.exe"",0"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Classes\Cadence.Installed.Media\shell\open\command"; ValueType: string; ValueData: """{app}\Cadence.exe"" ""%1"""; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Cadence\InstalledCapabilities"; ValueName: "ApplicationName"; ValueType: string; ValueData: "Cadence"; Flags: uninsdeletekey; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Cadence\InstalledCapabilities"; ValueName: "ApplicationDescription"; ValueType: string; ValueData: "Cadence video player and editor"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\Cadence\InstalledCapabilities"; ValueName: "ApplicationIcon"; ValueType: string; ValueData: """{app}\Cadence.exe"",0"; Tasks: filetypes
Root: HKA; Subkey: "{#RegistryBase}\RegisteredApplications"; ValueName: "Cadence.Installed"; ValueType: string; ValueData: "{#RegistryBase}\Cadence\InstalledCapabilities"; Flags: uninsdeletevalue; Tasks: filetypes
#include AssociationsFile

[Run]
Filename: "{app}\Cadence.exe"; Description: "{cm:LaunchCadence}"; Flags: postinstall unchecked nowait skipifsilent
Filename: "ms-settings:defaultapps"; Description: "{cm:DefaultApps}"; Flags: postinstall unchecked shellexec nowait skipifsilent; Tasks: filetypes

[Code]
var
  PreviousFiles: TArrayOfString;

procedure RemoveObsoleteFiles;
var
  CurrentFiles: TArrayOfString;
  I, J: Integer;
  RelativeName, Target, Digest: String;
  StillInstalled: Boolean;
begin
  if not LoadStringsFromFile(ExpandConstant('{app}\uninstall\installed-files.txt'), CurrentFiles) then Exit;
  for I := 0 to GetArrayLength(PreviousFiles) - 1 do begin
    if (Length(PreviousFiles[I]) < 66) or (Copy(PreviousFiles[I], 65, 1) <> '|') then Continue;
    Digest := Copy(PreviousFiles[I], 1, 64);
    RelativeName := Copy(PreviousFiles[I], 66, MaxInt);
    if (Pos('..', RelativeName) > 0) or (Pos(':', RelativeName) > 0) then Continue;
    if (Pos('_internal\', Lowercase(RelativeName)) <> 1) and (Pos('licences\', Lowercase(RelativeName)) <> 1) then Continue;
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
        if DeleteFile(Target) then Log('Removed obsolete installed file: ' + RelativeName);
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
  if CurStep = ssPostInstall then RemoveObsoleteFiles;
end;
