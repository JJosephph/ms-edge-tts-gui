; ============================================================
; 樺英雄语音合成助手 - Inno Setup 安装脚本
; 版本号：CI 通过 /DMyAppVersion 传入，本地兜底 1.0.0
; ============================================================

#define MyAppName "樺英雄语音合成助手"

; ★ 关键：未从命令行传入时才用兜底值，CI 的 /D 参数会覆盖这里
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

#define MyAppPublisher "HuaYingXiong"
#define MyAppExeName "HuayingxiongTTS.exe"
#define MyAppURL "https://github.com/sjhznh/ms-edge-tts-gui"

[Setup]
AppId={{CB391E63-6424-495D-8A55-36B8A4F8087D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\HuayingxiongTTS
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=HuayingxiongTTS-Setup
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
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
Name: "chinesesimp"; MessagesFile: "Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}:"

[Files]
; ★ 直接装"单文件版"，安装后改名成 HuayingxiongTTS.exe，无 _internal 依赖
Source: "..\dist\HuayingxiongTTS-Portable.exe"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{#MyAppURL}"; Description: "打开 GitHub 为开源项目点 Star"; Flags: nowait postinstall skipifsilent shellexec runasoriginaluser

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurPageChanged(CurPageID: Integer);
var
  IsZh: Boolean;
begin
  IsZh := ActiveLanguage() = 'chinesesimp';
  if CurPageID = wpWelcome then
  begin
    if IsZh then
      WizardForm.WelcomeLabel2.Caption :=
        '欢迎安装 {#MyAppName}（免费开源 MIT License）' + #13#10 +
        '已内置运行环境，装完即用。'
    else
      WizardForm.WelcomeLabel2.Caption :=
        'Welcome to {#MyAppName} (Free, MIT License)' + #13#10 +
        'Runtime bundled.';
  end;
end;
