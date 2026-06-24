# packaging/
> L2 | 父级: ../CLAUDE.md

分发打包：把源码形态的 VoiceLog 变成粉丝可下载安装的成品。macOS 已正式交付(签名+公证,Latest)；Windows 经 GitHub Actions CI 真实构建并发布(测试版,未签名)。

**发布约定**：每个正式版 Release 同带双平台安装包,资产用**固定名** `VoiceLog-macOS.dmg` / `VoiceLog-Windows.exe`(不带版本号),配合 `https://github.com/zhaozimin/Recorder/releases/latest/download/<固定名>` 给官网写死、永远拉最新。铁律:两条链接要都生效,二者必须挂在**同一个非 prerelease 的 Latest release** 内(`latest` 只认一个非预发布 release)。Windows 版本号与 macOS 独立演进。**完整发布仪式**(版本→记账→构建→公证→发布→自检 九步)见根 `CLAUDE.md` 的 `<release>` 段。

## 成员清单
- `macos/`: macOS 打包子模块(已可用)。PyInstaller → 签名 → 公证 → `.dmg`。
  - `VoiceLog.spec`: PyInstaller 配置。收集 mlx/torch/speechbrain/silero/sounddevice；arm64；
    BUNDLE 设 LSUIElement(无 Dock)+麦克风用途串+bundle id `com.zhaozimin.voicelog`+`NSAppSleepDisabled`(退 App Nap,
    闲置后点击即时响应——此 plist 是生产版 App 的唯一真相源,build-app.sh 仅改 CFBundleExecutable/删 LSUIElement,故必须写在这)。
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
  - `installer.iss`: Inno Setup,把 dist\VoiceLog 打成 `VoiceLog-Windows.exe`(**固定名**,无版本号,配合 Release `latest/download` 稳定链接;含开机自启选项)。
  - `make_ico.py` / `VoiceLog.ico`: 深色 squircle + 白 logo 的多尺寸 .ico(exe/安装器图标)。

## 关键设计：只读资源 vs 可写数据
打包版严守「bundle 只读、用户数据写 ~/Library/Application Support/VoiceLog」——主程序 `voicelog_menubar.py`
顶部按 `sys.frozen` 切换 RES/DATA。破坏这条=签名失效=Gatekeeper 拒运行。

法则: 成员完整·一行一文件·父级链接·macOS 本机签名(证书在钥匙串)、Windows 走 CI(无 Win 真机)。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
