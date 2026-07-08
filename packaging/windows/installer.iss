; Inno Setup script for the Fluke Community desktop app.
; Compile with: ISCC.exe packaging\windows\installer.iss
; Expects the PyInstaller one-dir build at dist\FlukeCommunity\ (build it first
; with packaging\windows\build_windows.ps1 or the PyInstaller spec directly).

#define AppName "Fluke Community"
#define AppVersion "0.1.0"
#define AppPublisher "Fluke Community (unofficial)"
#define AppExeName "FlukeCommunity.exe"
; SourceRoot / OutputRoot are resolved relative to this script's directory.
#define SourceDir "..\..\dist\FlukeCommunity"
#define IconFile "..\icons\fluke.ico"

[Setup]
AppId={{7F3B2C41-6C0E-4F5A-9B7A-3B9E1D2A8C10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\FlukeCommunity
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install so no admin elevation is required for tradespeople.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\..\dist\installer
OutputBaseFilename=FlukeCommunity-{#AppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#AppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
; Ship the entire PyInstaller one-dir output.
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
