; ─────────────────────────────────────────────────────────────────────────────
; steam_curator.iss — Inno Setup 6 installer script
;
; Produces: dist\installer\SteamCurator-{version}-Setup.exe
;
;   1. pyinstaller packaging\windows\steam_curator.spec --noconfirm --clean
;   2. "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DAppVersion=2.0.0 packaging\windows\steam_curator.iss
;      (release.yml passes the version from the git tag)
; ─────────────────────────────────────────────────────────────────────────────

#define AppName      "Steam Curator"
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define AppPublisher "PimpMySteam"
#define AppURL       "https://pimpmysteam.com"
#define RepoURL      "https://github.com/Huzzama/Steam-Curated"
#define AppExeName   "SteamCurator.exe"

; DO NOT change AppID after the first release — Inno uses it to detect upgrades
; and replace previous installs cleanly.
#define AppID        "{{7C1E6B2A-9D3F-4E58-A6B1-2F0C5D8E9A47}"

#define DistDir      "..\..\dist\SteamCurator"
#define IconFile     "..\..\assets\icon.ico"

[Setup]
AppId={#AppID}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#RepoURL}/issues
AppUpdatesURL={#RepoURL}/releases
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\..\dist\installer
OutputBaseFilename=SteamCurator-{#AppVersion}-Setup
Compression=lzma2/ultra64
SolidCompression=yes
VersionInfoVersion={#AppVersion}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} Installer
VersionInfoProductName={#AppName}
VersionInfoProductVersion={#AppVersion}
WizardStyle=modern
WizardResizable=yes
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
; per-user install without UAC by default; admins can pick system-wide
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
MinVersion=10.0
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon";   Description: "{cm:CreateDesktopIcon}";      GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startmenuicon"; Description: "Create a Start Menu shortcut"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}";           Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; logs only — wishlist, purchases, settings and creds in %APPDATA%\SteamCurator are kept
Type: filesandordirs; Name: "{userappdata}\SteamCurator\logs"
