# VoiceLog — 本地实时语音日志（macOS 菜单栏常驻）
Python 3.12(uv) + mlx-whisper(large-v3) + silero-vad + speechbrain(ECAPA) + sounddevice + rumps + launchd

把贴身 DJI Mic Mini 的语音实时转成当天 Markdown 日志。**音频绝不写盘，文字不上传**，全本地。

<directory>
voicelog/  - 应用本体 (主程序 voicelog_menubar.py + 声纹子模块 speaker.py + 配置 + 依赖 + 日志)
launchd/   - 开机自启：plist 与装载脚本 (登录即常驻，开发机自用)
packaging/ - 分发打包 (macos: PyInstaller+签名+公证→.dmg；windows: 移植脚手架+CI)
.github/   - GitHub Actions (build-windows.yml：windows-latest 出 .exe，待移植落地)
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

法则: 极简·稳定·导航·版本精确。音频即用即弃，单向数据流，门控便宜的先拦。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
