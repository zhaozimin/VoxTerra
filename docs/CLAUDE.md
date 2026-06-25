# docs/
> L2 | 父级: ../CLAUDE.md

README 视觉资产域：仅供 GitHub 主页 README 顶部 hero 展示用的素材。**与 voicelog/assets/(运行期菜单栏/Dock 图标) 和 packaging/macos/(打包 .icns/.ico 图标) 三域解耦**——README 只引用本目录，重排运行/打包资源不会打断主页展示，主页改版也不动产物图标。

## 成员清单
- `logo.png`: README hero logo。深色 squircle 应用图标(源自 `packaging/macos/VoiceLog_iconmaster.png`，1024x1024，自带深色背景，亮/暗主题皆稳)。README 顶部以 `<img width="160">` 居中引用。换图只需覆盖此文件，无需动 README。

法则: 成员完整·一行一文件·父级链接·README 资产单独成域，与运行/打包图标互不耦合。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
