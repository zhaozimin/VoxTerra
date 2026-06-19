# packaging/
> L2 | 父级: ../CLAUDE.md

分发打包：把源码形态的 VoiceLog 变成粉丝可下载安装的成品。macOS 已交付；Windows 是脚手架(待移植)。

## 成员清单
- `macos/`: macOS 打包子模块(已可用)。PyInstaller → 签名 → 公证 → `.dmg`。
  - `VoiceLog.spec`: PyInstaller 配置。收集 mlx/torch/speechbrain/silero/sounddevice；arm64；
    BUNDLE 设 LSUIElement(无 Dock)+麦克风用途串+bundle id `com.zhaozimin.voicelog`。
  - `entitlements.plist`: 硬化运行时豁免(allow-jit / allow-unsigned-executable-memory /
    disable-library-validation / audio-input)——公证强制开硬化运行时,而 Python/torch/mlx 需这些豁免才不崩。
  - `build.sh`: 一键 构建→由内向外深签(先 dylib/so 再 .app)→校验→打 DMG。需 Developer ID 证书在钥匙串。
  - `notarize.sh`: notarytool 提交公证(App+DMG)→stapler 装订(离线可验)。需 Apple ID 专用密码。
  - `make_icon.py`: 把品牌白 logo 合成深色 squircle → master PNG;配 sips/iconutil 产 `VoiceLog.icns`。
  - `VoiceLog.icns`: App/Dock/Finder/DMG 图标(make_icon.py 产物,提交入库供构建直接用)。
- `windows/`: Windows 移植脚手架(**未实现**)。
  - `PORT_PLAN.md`: 移植架构蓝图——平台差异收敛到 transcriber/tray/windows_ui 三接口,core 对平台无感。
  - `requirements-windows.txt`: Windows 依赖(faster-whisper/pystray/tkinter,去掉 mlx/rumps/pyobjc)。
  - `VoiceLog-win.spec` / `installer.iss`: PyInstaller + Inno Setup 骨架,待移植落地填实。

## 关键设计：只读资源 vs 可写数据
打包版严守「bundle 只读、用户数据写 ~/Library/Application Support/VoiceLog」——主程序 `voicelog_menubar.py`
顶部按 `sys.frozen` 切换 RES/DATA。破坏这条=签名失效=Gatekeeper 拒运行。

法则: 成员完整·一行一文件·父级链接·macOS 本机签名(证书在钥匙串)、Windows 走 CI(无 Win 真机)。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
