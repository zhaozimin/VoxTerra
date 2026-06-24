# 言壤（VoiceLog）— 本地实时语音日志（macOS 菜单栏 lite + SwiftUI 完整版 / Windows 测试版）
引擎 Python 3.12(uv) + mlx-whisper + silero-vad + speechbrain(ECAPA) + sounddevice + rumps；**前端 Swift/SwiftUI（macOS V1 旗舰，mac/）**；Windows 用 faster-whisper(CT2) + pystray

把贴身 DJI Mic Mini 的语音实时转成当天 Markdown 日志。**音频绝不写盘，文字不上传**，全本地。

<branding>
中文品牌名「言壤」，英文 VoiceLog。二者分工：
  显示名(用户所见) = 言壤 —— i18n 的 app_name(zh)、CFBundleName/CFBundleDisplayName、DMG 卷名、Windows 开始菜单/控制面板。
  机器名(稳定不可改) = VoiceLog —— .app/dmg/exe 磁盘与下载文件名、可执行名、安装目录、
    bundle id `com.zhaozimin.voicelog`、数据目录 `~/Library/Application Support/VoiceLog`。
铁律：机器名一旦改动 → 老用户数据/授权全失联。改名只动显示层，永不动机器层。
</branding>

<directory>
voicelog/  - 引擎+菜单栏外壳 (一套引擎两层外壳：菜单栏 lite / Dock 全窗口 full main_window.py + 声纹 speaker.py + 模型获取/续传 + 更新检查 + i18n + 原生窗口)
mac/       - **原生 SwiftUI 完整版（V1 旗舰）** (Sources/YanRang/*.swift：统一工具栏窗口+四页+菜单栏托盘+注册浮层；用 Process 拉起 voicelog headless 引擎作 sidecar；SPM 构建)
desktop/   - 已废弃 Tauri 版 (Rust/JS，历史存档，被 mac/ SwiftUI 取代，不再维护)
tests/     - 行为锚点 (标准库 unittest，钉死纯逻辑：版本比较/模型四态/下载续传锚点/自动更新/i18n/粘贴)
launchd/   - 开机自启：plist 与装载脚本 (登录即常驻，开发机自用)
packaging/ - 分发打包 (macos: PyInstaller+签名+公证→.dmg(build-app.sh 嫁接 SwiftUI)；windows: Inno Setup CI 构建→.exe 测试版)
.github/   - GitHub Actions (build-windows.yml：标准构建发 Release；build-windows-offline.yml：含模型离线版)
</directory>

<config>
README.md                  - 项目说明与快速上手
CHANGELOG.md               - 变更日志 (版本规则：小改 +0.1，大改 +1.0)
LICENSE                    - 许可证
本地24h语音日志系统-部署方案.md - 完整设计与部署方案
交给ClaudeCode-部署指令.md  - 给 Agent 的一键部署指令
.gitignore                 - 忽略 venv/模型/声纹档/logs
</config>

<runtime>
venv:   ~/voicelog-venv (uv hermetic CPython 3.12，绕开 Homebrew libexpat ABI 坑)
模型:   ~/voicelog-models/ (whisper-large-v3-mlx 用 aria2 直拉；ecapa 声纹模型 HF 缓存)
声纹档: ~/voicelog-models/speaker_profile.npy (注册后生成)
输出:   config.yaml 的 vault_path (默认外置 PCIe SSD，掉线回退 ~/voicelog-fallback)
</runtime>

<release>
发布仪式 —— 每次更新都按此套路推送，缺一不可：
1. 版本号(+0.1 小改 / +1.0 大改)：引擎 `voicelog/voicelog_menubar.py` 的 VERSION 与 `packaging/macos/VoiceLog.spec` 同步；SwiftUI 壳 `mac/bundle.sh`。
2. 记账：`CHANGELOG.md` 顶部加版本条目(病根 + 修法)。
3. 文档同构：改哪层同步哪层 CLAUDE.md(GEB 协议，禁孤立变更)。
4. 提交+推送：`git push origin main` → 打 `vX.Y.Z` tag 并 push。
5. 构建 macOS：`packaging/macos/build-app.sh`(PyInstaller 引擎 + 嫁接 SwiftUI + 由内向外深签 → `dist/VoiceLog-<ver>.dmg`)。
6. 公证：`packaging/macos/notarize.sh`(账号持有人 Apple ID + App 专用密码；开发者协议须保持已签，否则 403)。过线 = `stapler validate` 通过 + `spctl` 显 `Notarized Developer ID`。
7. 发布到 GitHub —— **统一 Latest release(铁律)**：一个 release 同带双平台包，资产**固定名** `VoiceLog-macOS.dmg` + `VoiceLog-Windows.exe`(无版本号)；`gh release create vX.Y.Z --latest`(非 prerelease)。Windows：CI 在 `vX.Y-win` tag 产出 `VoiceLog-Windows.exe`，手动取下挂进本统一 release。
8. 官网下载链接写死、永拉最新：`releases/latest/download/VoiceLog-macOS.dmg`、`.../VoiceLog-Windows.exe`。
9. 装机自检：旧 App 改名备份(`.bak-preXXXX`) → 装新版 → 验 `state.json` 的 version + 心跳。
铁律：未公证不发正式版；两平台包必同处**一个非 prerelease 的 Latest** release(`latest` 只认一个非预发布)；Windows 版本号与 macOS 独立演进；机器名/bundle id 永不改。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
</release>

法则: 极简·稳定·导航·版本精确。音频即用即弃，单向数据流，门控便宜的先拦。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
