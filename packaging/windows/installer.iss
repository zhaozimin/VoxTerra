; ============================================================================
;  VoiceLog · Windows 安装包脚本 (Inno Setup) —— 骨架,待移植落地后启用
;  把 PyInstaller 产出的 dist\VoiceLog\ 打成单文件安装程序。
;  TODO(移植时): 确认 dist 路径;补 .ico;可选「开机自启」复选框写注册表 Run 键。
; ============================================================================
#define MyAppName "VoiceLog"
#define MyAppVersion "0.8.0"
#define MyAppPublisher "Zimin Zhao"
#define MyAppExeName "VoiceLog.exe"

[Setup]
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputDir=Output
OutputBaseFilename=VoiceLog-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
PrivilegesRequired=lowest

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
; PyInstaller onedir 产物整目录打入
Source: "..\..\dist\VoiceLog\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{userstartup}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startup

[Tasks]
Name: "startup"; Description: "开机自动启动 VoiceLog"; GroupDescription: "附加任务:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动 VoiceLog"; Flags: nowait postinstall skipifsilent
