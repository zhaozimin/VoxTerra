# VoiceLog · Windows 移植方案 (脚手架)

> 状态: **未实现，骨架就绪**。macOS 版已交付；Windows 是一次真正的移植，非重新打包。
> 本文是移植的架构蓝图 + CI 跑道。决定推进时，按此落地即可。

## 一、为什么是「移植」而非「打包」

核心三件套是 macOS 独占的，Windows 上**根本不存在**：

| 关注点 | macOS 现状 | Windows 替换 | 难度 |
|---|---|---|---|
| 转写引擎 | `mlx-whisper`（Apple MLX 独占） | `faster-whisper`（CTranslate2，CPU/CUDA） | 中 |
| 菜单栏/托盘 | `rumps`（AppKit） | `pystray` | 中 |
| 注册/纠错窗口 | PyObjC Cocoa | `tkinter`（内置，朴素够用） | 中 |
| 自启 | launchd | 注册表 Run 键 / 启动文件夹快捷方式 | 低 |

跨平台**已经能直接复用**的内核（无需改）：`sounddevice`、`silero-vad`、`speechbrain`、
三道门控逻辑、`i18n`、写盘逻辑、复读/幻觉过滤、关键词纠错。

## 二、抽象边界（落地时的唯一正确切法）

不要 `if platform` 散落各处——那是坏品味。把平台差异**收敛到三个接口**，主流程对平台无感：

```
voicelog/
  core/                  # 纯逻辑,零平台依赖(从现 voicelog_menubar.py 抽出)
    pipeline.py          # 采集→VAD→三道门→转写→过滤→写盘(已跨平台)
    gating.py  speaker.py  i18n.py  corrections.py  paths.py
  platform/
    transcriber.py       # 接口: transcribe(wav_f32_16k, language, prompt) -> str
      ├─ transcriber_mlx.py      (macOS: mlx_whisper)
      └─ transcriber_fw.py       (Windows/Linux: faster_whisper)
    tray.py              # 接口: 菜单项/标题/图标/回调
      ├─ tray_rumps.py           (macOS)
      └─ tray_pystray.py         (Windows/Linux)
    windows_ui.py        # 注册/纠错窗口
      ├─ ui_cocoa.py             (macOS: 现 enroll_ui/replace_ui)
      └─ ui_tk.py                (Windows/Linux: tkinter)
  app.py                 # 组装:按 sys.platform 选实现,跑 core.pipeline
```

入口按平台装配实现，`core` 永不 import 任何平台库。这样 Windows 移植 = 只写 `*_fw.py`
/ `*_pystray.py` / `*_tk.py` 三组实现，内核一行不动。

## 三、faster-whisper 对接要点

- 模型: `Systran/faster-whisper-large-v3`（或 `...-large-v3-turbo`），首次运行自动下载到 HF 缓存。
- 设备: 有 N 卡 → `device="cuda", compute_type="float16"`；否则 `device="cpu", compute_type="int8"`。
  **CPU 上 large-v3 难实时**——Windows 版应默认 turbo + int8，并在 README 标注「建议 N 卡」。
- 接口契约与 mlx 完全一致：吃 16k float32 单声道 ndarray，吐文本。`initial_prompt` 同名直传。

## 四、CI 跑道（已就绪）

`.github/workflows/build-windows.yml`：在 `windows-latest` 上 `pip install` →
PyInstaller 打包 → Inno Setup 生成 `.exe` 安装包 → 打 tag 时附加到 GitHub Release。

触发：手动 `workflow_dispatch` 或推送到 `windows-port` 分支（移植期不污染主分支 CI）。

落地清单（按序）：
1. 抽 `core/`（从现 `voicelog_menubar.py` 拆出纯逻辑，macOS 版同步切到新结构并回归测试）。
2. 写三组平台实现（先 `transcriber_fw.py`，最关键）。
3. 写 `packaging/windows/VoiceLog-win.spec` 的真实内容 + `installer.iss`。
4. 开 `windows-port` 分支推上去，让 CI 出第一个 `.exe`，找 Windows 用户实测。
5. 稳定后合并、打 `vX.Y-win` tag，CI 自动挂到 Release。

## 五、诚实的风险（移植前必须知道）

- **无法在 Mac 上运行测试**：CI 只能保证「构建成功」，跑没跑起来需 Windows 真机验证。
- **无 Windows 代码签名证书**：用户首次运行被 SmartScreen 警告「未知发布者」；要消除需单独购买 EV/OV 证书并注入 CI Secret。
- **性能**：无 N 卡时 CPU 转写可能跟不上实时，需降级到 turbo/int8 或更小模型。

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
