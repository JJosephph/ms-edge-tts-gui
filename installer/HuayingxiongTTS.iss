; ============================================================
; 樺英雄语音合成助手 - Inno Setup 安装脚本
; ============================================================

#define MyAppName "樺英雄语音合成助手"
#ifndef MyAppVersion
#define MyAppVersion "1.7.9"
#endif
#define MyAppPublisher "HuaYingXiong"
#define MyAppExeName "HuayingxiongTTS.exe"
#define MyAppURL "https://github.com/sjhznh/ms-edge-tts-gui"
; 关键：用 SourcePath 宏锚定路径，避免 CI 相对路径解析错误
#define BasePath "{#SourcePath}\.."

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
OutputDir={#BasePath}\dist
OutputBaseFilename=HuayingxiongTTS-Setup
; 注释 icon 测试（若此文件缺失必挂）
; SetupIconFile={#BasePath}\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 注释 license 测试（若此文件缺失必挂）
; LicenseFile={#BasePath}\LICENSE
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
; 主程序目录（日志已确认存在）
Source: "{#BasePath}\dist\HuayingxiongTTS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 暂时注释 license 文件打包
; Source: "{#BasePath}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
; Source: "{#BasePath}\LICENSE.zh.txt"; DestDir: "{app}"; Flags: ignoreversion

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
      WizardForm.WelcomeLabel2.Caption := '欢迎安装 {#MyAppName}（免费开源 MIT License）' + #13#10 + '已内置运行环境，装完即用。'
    else
      WizardForm.WelcomeLabel2.Caption := 'Welcome to {#MyAppName} (Free, MIT License)' + #13#10 + 'Runtime bundled.';
  end;
end;
