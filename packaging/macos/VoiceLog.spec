# -*- mode: python ; coding: utf-8 -*-
# ============================================================================
#  VoiceLog · macOS .app 打包配置 (PyInstaller)
#  产出: dist/VoiceLog.app —— 菜单栏 App(LSUIElement,无 Dock),Apple Silicon(arm64)。
#  模型不打包(首次运行联网下载),保证 .dmg 稳在 GitHub Release 单文件 2G 上限内。
#  [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
# ============================================================================
import os
from PyInstaller.utils.hooks import collect_all, collect_submodules

SPEC_DIR = os.path.abspath(SPECPATH)                       # packaging/macos
PROJ = os.path.abspath(os.path.join(SPEC_DIR, "..", ".."))  # 仓库根
SRC = os.path.join(PROJ, "voicelog")                       # 源码目录

datas, binaries, hiddenimports = [], [], []

# --- 重 ML 依赖:整包收集(hook 抓不全的 metallib / jit 模型 / yaml 超参) ---
for pkg in ("mlx", "mlx_whisper", "speechbrain", "silero_vad", "sounddevice"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

# torch 体量巨大,交给 PyInstaller 内置 torch hook 处理(收集其 dylib 与数据)。

# --- 项目自身只读资源 ---
datas += [
    (os.path.join(SRC, "assets"), "assets"),
    (os.path.join(SRC, "config.example.yaml"), "."),
]

# --- 动态/懒加载导入:静态分析抓不到,显式补 ---
hiddenimports += [
    "speechbrain.inference.speaker",   # speaker.py 里函数内懒导入
    "objc", "AppKit", "Foundation", "PyObjCTools",  # rumps + 原生窗口
    "sklearn",                          # speechbrain 部分路径会用到
]
hiddenimports += collect_submodules("speechbrain")

a = Analysis(
    [os.path.join(SRC, "voicelog_menubar.py")],
    pathex=[SRC],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide2",
              "PySide6", "IPython", "pytest", "notebook", "jupyter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="VoiceLog",
    console=False,                 # 窗口型 App,无终端
    disable_windowed_traceback=False,
    target_arch="arm64",           # mlx 仅 Apple Silicon
    codesign_identity=None,        # 签名交给 build.sh(由内向外深签)
    entitlements_file=None,
)

coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="VoiceLog")

app = BUNDLE(
    coll,
    name="VoiceLog.app",
    icon=os.path.join(SPEC_DIR, "VoiceLog.icns"),
    bundle_identifier="com.zhaozimin.voicelog",
    version="0.8.0",
    info_plist={
        "CFBundleName": "VoiceLog",
        "CFBundleDisplayName": "VoiceLog",
        "CFBundleShortVersionString": "0.8.0",
        "CFBundleVersion": "0.8.0",
        "LSUIElement": True,                 # 菜单栏常驻,无 Dock 图标
        "LSMinimumSystemVersion": "13.0",
        "NSMicrophoneUsageDescription":
            "VoiceLog 需要访问麦克风,在本机实时把你的语音转成文字日志;音频从不离开你的电脑。",
        "NSHumanReadableCopyright": "© 2026 Zimin Zhao",
        "CFBundlePackageType": "APPL",
    },
)
