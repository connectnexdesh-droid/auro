#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define AppName "AURO"

[Setup]
AppId={{A6D7D3A8-5B42-4F1E-8E91-8A9D45A0C6B2}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=AURO
DefaultDirName={localappdata}\Programs\AURO
DefaultGroupName=AURO
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AURO-Setup-{#AppVersion}
SetupIconFile=assets\auro.ico
UninstallDisplayIcon={app}\AURO.exe
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "..\dist\AURO\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AURO"; Filename: "{app}\AURO.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\AURO"; Filename: "{app}\AURO.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\AURO.exe"; Description: "Launch AURO"; Flags: nowait postinstall skipifsilent
