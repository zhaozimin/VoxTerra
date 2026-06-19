# Recorder · VoiceLog — 本地实时语音日志

> 随身麦克风 → 本地 Whisper 实时转写 → Markdown 笔记。macOS 菜单栏常驻,**音频绝不写盘,文字永不上传**。

把一整天随口说的话,自动变成带时间戳的文字日志,落进你自己的文件夹(可接 Obsidian)。全程在本机的 Apple Silicon 上跑,不联网、不烧 API、零成本。

## ✨ 特性

- **全本地 / 零成本**：转写跑在本机 MLX 上,不调任何云端 API,断网照跑。
- **隐私优先**：音频转写完即丢,**从不写盘**;文字只进你的本地文件夹,**永不上传**。
- **整句转写**：Silero VAD 按「一句话」切分,停顿即落字,日志干净有标点(非逐字流式)。
- **菜单栏常驻**：无 Dock 图标、不抢前台。计数 / 暂停 / 打开笔记 / 切时区 / 改保存位置。
- **专名识别增强**：术语偏置(`initial_prompt`)+ 词边界纠错(`replace`)+ 幻觉过滤,治「Claude→Cloud」「流式→流逝」。
- **时区随切**：全球飞,菜单栏点一下换时区,时间戳与「当天」立刻跟上。
- **掉盘不丢字**：输出目录在外置盘上、盘掉线时,自动回退内置盘,菜单栏 🟠 提示。

## 🧱 要求

- Apple Silicon Mac(M 系列)+ macOS
- Python ≥ 3.10(安装脚本会用 uv 自动准备一个 hermetic 3.12)
- 一支麦克风(原项目用 DJI Mic Mini,任何输入设备都行)

## 📥 下载安装（推荐）

去 [**Releases**](https://github.com/zhaozimin/Recorder/releases) 下载最新 `VoiceLog-x.y.z.dmg`，双击打开，把 **VoiceLog** 拖进「应用程序」即可。

- **要求**：Apple Silicon Mac（M 系列）+ macOS 13 以上。
- **首次启动**：会弹「VoiceLog 想访问麦克风」→ 点**允许**；之后它常驻菜单栏（无 Dock 图标）。
- **首次转写**：会联网下载一次语音模型（约 1–2 GB，仅此一次），之后全离线。
- 已 Apple 公证，双击直接开；若想开机自启，到「系统设置 → 通用 → 登录项」把 VoiceLog 加上。

> Windows 版正在移植中（核心引擎是 Apple 独占的，需换转写后端，见 `packaging/windows/PORT_PLAN.md`）。

## 🚀 从源码运行（开发者）

```bash
git clone https://github.com/zhaozimin/Recorder.git
cd Recorder
cp voicelog/config.example.yaml voicelog/config.yaml   # 按需改配置
bash voicelog/install.sh
```

装完两步手动收尾:① 前台跑一次主程序授予麦克风权限;② `launchctl load` 启用后台自启。详见 [voicelog/README.md](voicelog/README.md)。

自己打安装包：`bash packaging/macos/build.sh`（需 Developer ID 证书），再 `bash packaging/macos/notarize.sh`（需 Apple ID 专用密码）公证。

## ⚙️ 配置(`voicelog/config.yaml`)

| 键 | 作用 |
|---|---|
| `vault_path` | 文字稿保存目录(菜单栏「保存位置」可随时改) |
| `model` | 本地模型目录绝对路径(最稳),或 HF 仓库名(联网下载) |
| `timezone` / `timezone_choices` | 时区与菜单栏候选(留空=跟随系统) |
| `input_device` | 麦克风(`null`=默认,编号,或名字片段) |
| `initial_prompt` | 术语偏置表(抬高专名先验,压繁体) |
| `replace` | 精确纠错(ASCII 词按词边界,不误伤) |
| `fallback_path` | 外置盘掉线时的内置回退目录 |

## 🔒 隐私

音频只在内存中转写、转完即弃,**不产生任何 `.wav`**;文字只写入你本地的笔记文件夹。唯一的联网是首次下载模型权重。可选的「夜间整理」(用云端 Claude 把当天文字整理成日志/推文)是单独开关,核心录音转写永远本地。

## 📦 打包成 App

已支持 `.app` 双击即用：PyInstaller 打包 + Developer ID 签名 + Apple 公证 → `.dmg`。
配置、日志、声纹落在 `~/Library/Application Support/VoiceLog`（bundle 只读，签名安全）；模型首次运行联网下载。
脚本见 [`packaging/macos/`](packaging/macos)，Windows 移植蓝图见 [`packaging/windows/PORT_PLAN.md`](packaging/windows/PORT_PLAN.md)。

## 📝 License

[MIT](LICENSE) © 2026 zhaozimin
