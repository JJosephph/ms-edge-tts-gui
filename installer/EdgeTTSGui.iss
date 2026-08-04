; ============================================================
; Edge TTS 语音合成助手 - Inno Setup 安装脚本
; 使用前请先运行 build_release.bat 生成 dist\EdgeTTSGui\
; ============================================================

#define MyAppName "Edge TTS 语音合成助手"
#ifndef MyAppVersion
#define MyAppVersion "1.0.1"
#endif
#define MyAppPublisher "WangYufan"
#define MyAppExeName "EdgeTTSGui.exe"
#define MyAppURL "https://github.com/JJosephph/ms-edge-tts-gui"

[Setup]
AppId={{CB391E63-6424-495D-8A55-36B8A4F8087D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\EdgeTTSGui
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=EdgeTTSGui-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
PrivilegesRequired=admin
SetupLogging=yes
CloseApplications=yes
VersionInfoVersion={#MyAppVersion}
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName}
VersionInfoProductName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "..\dist\EdgeTTSGui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent
Filename: "{#MyAppURL}"; Description: "Open GitHub and ⭐ Star the open-source project"; Flags: nowait postinstall skipifsilent unchecked

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurPageChanged(CurPageID: Integer);
begin
  if CurPageID = wpWelcome then
  begin
    WizardForm.WelcomeLabel1.Caption := 'Welcome to {#MyAppName}';
    WizardForm.WelcomeLabel2.Caption := 'This is an open-source project by WangYufan.' + #13#10 + #13#10 +
      'No Python required - the runtime is bundled. Install & use right away.' + #13#10 + #13#10 +
      'Click Next to choose an install location (any drive), then install.';
  end;
  if CurPageID = wpFinished then
  begin
    WizardForm.FinishedLabel.Caption := 'Installation completed!' + #13#10 + #13#10 +
      'Enjoy the open-source project? Please ⭐ Star it on GitHub to support us!' + #13#10 +
      'Feedback and issues are also welcome at the repository.';
  end;
end;
