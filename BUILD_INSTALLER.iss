#define MyAppName "A-BEATS"
#define MyAppVersion "1.2.0"
#define MyAppPublisher "A-BEATS"
#define MyAppExeName "A-BEATS.exe"

[Setup]
AppId={{A8D4A90C-6B4D-4B50-9A18-ABEA71000001}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={localappdata}\Programs\A-BEATS
DefaultGroupName={#MyAppName}
OutputDir=installer_output
OutputBaseFilename=A-BEATS-Setup-{#MyAppVersion}-x64
SetupIconFile=assets\a_beats.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительные ярлыки:"; Flags: unchecked

[Files]
Source: "dist\A-BEATS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "PRIVACY.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\A-BEATS"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\A-BEATS"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Запустить A-BEATS"; Flags: postinstall nowait skipifsilent
