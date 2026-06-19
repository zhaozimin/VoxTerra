# -*- mode: python ; coding: utf-8 -*-
# ============================================================================
#  VoiceLog · Windows 打包配置 (PyInstaller) —— 骨架,待移植落地后填实
#  依赖移植后的跨平台入口 voicelog/app.py(见 PORT_PLAN.md)。
#  TODO(移植时): 入口指向 app.py;collect faster_whisper/ctranslate2/pystray;
#                图标用 .ico;onedir + Inno Setup 出安装包。
# ============================================================================
import os
from PyInstaller.utils.hooks import collect_all

SPEC_DIR = os.path.abspath(SPECPATH)
PROJ = os.path.abspath(os.path.join(SPEC_DIR, "..", ".."))
SRC = os.path.join(PROJ, "voicelog")

datas, binaries, hiddenimports = [], [], []
for pkg in ("faster_whisper", "ctranslate2", "silero_vad", "sounddevice",
            "speechbrain", "pystray", "PIL"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

datas += [(os.path.join(SRC, "assets"), "assets"),
          (os.path.join(SRC, "config.example.yaml"), ".")]

a = Analysis(
    [os.path.join(SRC, "app.py")],          # TODO: 移植后的跨平台入口
    pathex=[SRC], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
    excludes=["mlx", "mlx_whisper", "rumps", "AppKit", "Foundation", "objc"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="VoiceLog",
          console=False, icon=os.path.join(SPEC_DIR, "VoiceLog.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="VoiceLog")
