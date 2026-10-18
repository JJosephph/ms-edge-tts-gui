; ============================================================
; 樺英雄语音合成助手 - Inno Setup 安装脚本
; 免费开源（MIT License）· 开发者 HuaYingXiong · 支持卸载
; ============================================================

#define MyAppName "樺英雄语音合成助手"
#ifndef MyAppVersion
#define MyAppVersion "1.7.0"
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
AppComments=Free open-source software (MIT License) / 免费开源软件（MIT License）
AppCopyright=Copyright (c) 2026 HuaYingXiong (QQ 562297979)
DefaultDirName={autopf}\HuayingxiongTTS
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=HuayingxiongTTS-Setup
; 关键修复：用绝对路径宏确保 CI 能找到
SetupIconFile={#SourcePath}\..\assets\app.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
UninstallDisplayName={#MyAppName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; 关键修复：用 {#SourcePath} 宏
LicenseFile={#SourcePath}\..\LICENSE
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
Name: "chinesesimp"; MessagesFile: "Languages\ChineseSimplified.isl"; LicenseFile: "{#SourcePath}\..\LICENSE.zh.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; LicenseFile: "{#SourcePath}\..\LICENSE"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}:"

[Files]
Source: "{#SourcePath}\..\dist\HuayingxiongTTS\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourcePath}\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourcePath}\..\LICENSE.zh.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{#MyAppURL}"; Description: "打开 GitHub 为开源项目点 Star / Open GitHub and Star the open-source project"; Flags: nowait postinstall skipifsilent shellexec runasoriginaluser

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
    begin
      WizardForm.WelcomeLabel1.Caption := '欢迎安装 {#MyAppName}';
      WizardForm.WelcomeLabel2.Caption := '这是一款免费、开源的桌面软件（MIT License），开发者：HuaYingXiong（QQ 562297979）。' + #13#10 + #13#10 +
        '已内置 Python 运行环境，无需额外安装，装完即可使用。' + #13#10 + #13#10 +
        '仓库地址：https://github.com/sjhznh/ms-edge-tts-gui' + #13#10 +
        '点击"下一步"选择安装位置（任意磁盘或文件夹），然后开始安装。';
    end
    else
    begin
      WizardForm.WelcomeLabel1.Caption := 'Welcome to {#MyAppName}';
      WizardForm.WelcomeLabel2.Caption := 'A free, open-source desktop app (MIT License) by HuaYingXiong (QQ 562297979).' + #13#10 + #13#10 +
        'No Python required - the runtime is bundled. Install & use right away.' + #13#10 + #13#10 +
        'Repository: https://github.com/sjhznh/ms-edge-tts-gui' + #13#10 +
        'Click Next to choose an install location (any drive), then install.';
    end;
  end;
  if CurPageID = wpFinished then
  begin
    if IsZh then
    begin
      WizardForm.FinishedLabel.Caption := '安装完成！' + #13#10 + #13#10 +
        '觉得这个开源项目好用？请到 GitHub 点个 Star 支持我们：' + #13#10 +
        'https://github.com/sjhznh/ms-edge-tts-gui' + #13#10 +
        '欢迎在仓库提交反馈或 Issue。';
    end
    else
    begin
      WizardForm.FinishedLabel.Caption := 'Installation completed!' + #13#10 + #13#10 +
        'Enjoy this open-source project? Please Star it on GitHub to support us:' + #13#10 +
        'https://github.com/sjhznh/ms-edge-tts-gui' + #13#10 +
        'Feedback and issues are also welcome.';
    end;
  end;
end;
