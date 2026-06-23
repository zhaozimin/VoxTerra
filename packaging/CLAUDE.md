# packaging/
> L2 | 父级: ../CLAUDE.md

分发打包：把源码形态的 VoiceLog 变成粉丝可下载安装的成品。macOS 已正式交付(签名+公证,Latest)；Windows 经 GitHub Actions CI 真实构建并发布(测试版,未签名)。

## 成员清单
- `macos/`: macOS 打包子模块(已可用)。PyInstaller → 签名 → 公证 → `.dmg`。
  - `VoiceLog.spec`: PyInstaller 配置。收集 mlx/torch/speechbrain/silero/sounddevice；arm64；
    BUNDLE 设 LSUIElement(无 Dock)+麦克风用途串+bundle id `com.zhaozimin.voicelog`。
  - `entitlements.plist`: 硬化运行时豁免(allow-jit / allow-unsigned-executable-memory /
    disable-library-validation / audio-input)——公证强制开硬化运行时,而 Python/torch/mlx 需这些豁免才不崩。
  - `build.sh`: 一键 构建→由内向外深签(先 dylib/so 再 .app)→校验→打 DMG。需 Developer ID 证书在钥匙串。
  - `build-app.sh`: **完整 App 统一构建(V1)**。以 PyInstaller 的 VoiceLog.app(引擎+运行时)为底座,嫁接 `../../mac` 的 SwiftUI 可执行 YanRang+dylib+资源,主入口改 YanRang(它拉起同包内引擎 Contents/MacOS/VoiceLog, headless),去 LSUIElement→由内向外深签→DMG「言壤-<ver>.dmg」。前置:先跑 build.sh 的 PyInstaller 步骤生成 dist/VoiceLog.app。
  - `notarize.sh`: notarytool 提交公证(App+DMG)→stapler 装订(离线可验)。需 Apple ID 专用密码。
  - `make_icon.py`: 把品牌白 logo 合成深色 squircle → master PNG;配 sips/iconutil 产 `VoiceLog.icns`。
  - `VoiceLog.icns`: App/Dock/Finder/DMG 图标(make_icon.py 产物,提交入库供构建直接用)。
- `windows/`: Windows 实验版(**Beta 已发布**,经 CI 构建发 Release;未签名,首启 SmartScreen 需放行)。入口 `voicelog/voicelog_win.py`。
  - `PORT_PLAN.md`: 移植方案 + 实现现状 + 已知债(大脑暂复制未共享)。
  - `requirements-windows.txt`: Windows 依赖(faster-whisper/pystray,去掉 mlx/rumps/pyobjc)。
  - `VoiceLog-win.spec`: PyInstaller(收集 faster_whisper/ctranslate2/silero/sounddevice/speechbrain/pystray,
    排除 mlx/rumps/pyobjc;hiddenimport `pystray._win32`)。
  - `installer.iss`: Inno Setup,把 dist\VoiceLog 打成 `VoiceLog-x.y.z-Setup.exe`(含开机自启选项)。
  - `make_ico.py` / `VoiceLog.ico`: 深色 squircle + 白 logo 的多尺寸 .ico(exe/安装器图标)。

## 关键设计：只读资源 vs 可写数据
打包版严守「bundle 只读、用户数据写 ~/Library/Application Support/VoiceLog」——主程序 `voicelog_menubar.py`
顶部按 `sys.frozen` 切换 RES/DATA。破坏这条=签名失效=Gatekeeper 拒运行。

法则: 成员完整·一行一文件·父级链接·macOS 本机签名(证书在钥匙串)、Windows 走 CI(无 Win 真机)。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
