#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖标准库 urllib/zipfile/shutil/tempfile;模型 zip 托管在本项目 GitHub Release
[OUTPUT]: 对外提供 model_ready / model_status_key / download_model / MAC_MODEL_URL / WIN_MODEL_URL / model_hint
[POS]: 跨平台「模型获取」中枢,被 voicelog_menubar.py(mac) 与 voicelog_win.py(win) 共用。
       不走 HuggingFace/镜像(国内不稳)——直接从我们自己的 GitHub Release 拉 zip,我可控、国内可达、可手动下。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

设计哲学:把「模型在哪、怎么来」收敛到一处。三种到手方式统一收口——
  ① 已存在本地(用户下过/离线版内置) → 直接用,不重下
  ② 缺失 → 从 GitHub Release 下载 zip,带进度,原子解压
  ③ 下不动 → 调用方给清晰指引(手动下 zip + 放进文件夹)
"""
import shutil
import tempfile
import zipfile
import urllib.request
from pathlib import Path

# 模型托管位置:本项目 GitHub Release 的 `models` tag(我可控、国内可达、可续传/手动下)
GITHUB_MODELS_BASE = "https://github.com/zhaozimin/Recorder/releases/download/models"
MAC_MODEL_URL = GITHUB_MODELS_BASE + "/whisper-mlx-turbo.zip"   # macOS / MLX
WIN_MODEL_URL = GITHUB_MODELS_BASE + "/whisper-ct2-turbo.zip"   # Windows / faster-whisper(CT2)


_MIN_WEIGHT = 1 << 20   # 1MB:whisper 权重均数百 MB,远高于此 → 挡住零字节/截断残留冒充就绪


def model_ready(model_dir) -> bool:
    """目录里有「足量」权重才算就绪。mlx: weights.*(.npz/.safetensors);CT2: model.bin。
    带最小体积校验:中断/零字节残留通不过存在性以外的这道门。"""
    d = Path(model_dir)
    if not d.is_dir():
        return False
    if any(w.stat().st_size >= _MIN_WEIGHT for w in d.glob("weights.*")):
        return True
    mb = d / "model.bin"
    return mb.exists() and mb.stat().st_size >= _MIN_WEIGHT


def model_status_key(downloading: bool, ready: bool, managed: bool) -> str:
    """模型四态 → i18n 键。单一真相源,mac/win 的 _model_title 共用,可穷举单测。
    下载中 > 已就绪 > 托管缺失(可下载) > 直连缺失(配置错)。"""
    if downloading:
        return "model_dling"     # ⏳ 正在下载 X%
    if ready:
        return "model_check"     # 🟢 已就绪
    if managed:
        return "model_get"       # ⬇ 缺失·托管·点此下载
    return "model_missing"       # ⚠️ 缺失·直连·路径配错


def _find_model_root(d: Path) -> Path:
    """zip 内可能多套一层目录——找到真正含权重的那层。"""
    if model_ready(d):
        return d
    for sub in d.iterdir() if d.is_dir() else []:
        if sub.is_dir() and model_ready(sub):
            return sub
    return d


def download_model(url: str, dest_dir, progress_cb=None) -> bool:
    """从 url 下载 zip(带进度回调 0~1)→ 解压到临时区 → 原子替换 dest_dir。成功返回 True。
    任何异常都吞掉返回 False(调用方据此给手动指引),绝不让下载失败把程序拖崩。"""
    dest = Path(dest_dir)
    tmp_zip = Path(tempfile.gettempdir()) / (dest.name + ".part.zip")
    tmp_ext = None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VoiceLog"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp_zip, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)        # 1MB/块
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(min(1.0, done / total))
        if total and done != total:
            return False          # 连接中途断开:字节数对不上 → 别拿截断的 zip 去解压
        tmp_ext = Path(tempfile.mkdtemp())
        with zipfile.ZipFile(tmp_zip) as z:
            z.extractall(tmp_ext)
        src = _find_model_root(tmp_ext)
        if not model_ready(src):
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(src), str(dest))
        return model_ready(dest)
    except Exception:
        return False
    finally:
        try:
            tmp_zip.unlink()
        except Exception:
            pass
        if tmp_ext:
            shutil.rmtree(tmp_ext, ignore_errors=True)


def model_hint(url: str, dest_dir) -> str:
    """下载失败时给用户的手动指引(中文)。"""
    return (f"自动下载失败。请手动下载模型：\n\n"
            f"1. 用浏览器打开（国内可访问）：\n   {url}\n"
            f"2. 解压后，把里面的文件夹放到：\n   {dest_dir}\n"
            f"3. 重新打开本应用即可。\n\n"
            f"（或下载「全离线版」安装包，内置模型，无需此步。）")
