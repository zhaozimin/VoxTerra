#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖标准库 urllib/subprocess/tempfile/pathlib；依赖 update_check 的 REPO；macOS 的 codesign/spctl/hdiutil/ditto
[OUTPUT]: 对外提供 asset_url / app_bundle_root / download_file / verify_macos_app / apply_macos / run_windows_installer / TEAM_ID
[POS]: 「真·自动更新」执行层。update_check 负责「有没有新版」，本模块负责「下载→校验→覆盖→重启」。
       纯函数(URL 拼装/.app 根推断)可单测；副作用函数防御式，任何失败都不破坏现有安装。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

安全第一：覆盖前必过三关——codesign 签名完整 + spctl 公证放行 + TeamIdentifier 是我们本人。
  三关任一不过立即中止，旧版原封不动。替换用「ditto 旁拷 + 原子重命名 + 失败回滚」，断点不致砖。
"""
import os
import tempfile
import subprocess
import urllib.request
from pathlib import Path

import update_check

TEAM_ID = "NNB86K8P8S"   # Developer ID Application: Zimin Zhao —— 只认本人签名的更新包
_DL_BASE = f"https://github.com/{update_check.REPO}/releases/download"


# ============================================================================
#  纯函数：下载地址拼装 / 从可执行路径推 .app 根（可单测）
# ============================================================================
def asset_url(version: str, plat: str) -> str:
    """版本号 → 在线安装包下载直链。命名须与发布脚本一致。
    mac: tag v{ver} 的 VoiceLog-{ver}.dmg；win: tag v{ver}-win-beta 的 VoiceLog-{ver}-Setup.exe。"""
    v = version.lstrip("vV")
    if plat == "win":
        return f"{_DL_BASE}/v{v}-win-beta/VoiceLog-{v}-Setup.exe"
    return f"{_DL_BASE}/v{v}/VoiceLog-{v}.dmg"


def app_bundle_root(executable: str):
    """从 sys.executable 上溯找到 .app 根；非打包(源码运行)路径里没有 .app → None。"""
    p = Path(executable)
    for cand in [p, *p.parents]:
        if cand.suffix == ".app":
            return str(cand)
    return None


# ============================================================================
#  下载：流式 + 完整性校验（断点/截断即失败）
# ============================================================================
def download_file(url: str, dest, progress_cb=None, timeout: float = 60) -> bool:
    dest = Path(dest)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VoiceLog"})
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress_cb and total:
                    progress_cb(min(1.0, done / total))
        if total and done != total:
            return False
        tmp.replace(dest)
        return True
    except Exception:
        return False
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass


# ============================================================================
#  macOS：覆盖前三关校验（安全闸）
# ============================================================================
def verify_macos_app(app_path: str, team_id: str = TEAM_ID) -> bool:
    """三关全过才算可信：① codesign 签名结构完整 ② spctl 公证/Gatekeeper 放行 ③ TeamID 是本人。"""
    try:
        if subprocess.run(["codesign", "--verify", "--deep", "--strict", app_path],
                          capture_output=True).returncode != 0:
            return False
        if subprocess.run(["spctl", "-a", "-t", "exec", "-vv", app_path],
                          capture_output=True).returncode != 0:
            return False
        r = subprocess.run(["codesign", "-dvv", app_path], capture_output=True, text=True)
        return f"TeamIdentifier={team_id}" in (r.stdout + r.stderr)
    except Exception:
        return False


_HELPER = r"""#!/bin/bash
# 等旧进程退出 → 原子替换 → 卸载 dmg → 重启。任何替换失败都回滚，绝不留下半个 App。
PID="$1"; INSTALLED="$2"; NEW="$3"; MNT="$4"
for i in $(seq 1 120); do /bin/kill -0 "$PID" 2>/dev/null || break; sleep 0.5; done
BAK="$INSTALLED.bak.$$"; STAGE="$INSTALLED.new.$$"
if /usr/bin/ditto "$NEW" "$STAGE"; then
  if /bin/mv "$INSTALLED" "$BAK" 2>/dev/null; then
    if /bin/mv "$STAGE" "$INSTALLED" 2>/dev/null; then
      /bin/rm -rf "$BAK"
    else
      /bin/mv "$BAK" "$INSTALLED"        # 回滚
      /bin/rm -rf "$STAGE"
    fi
  else
    /bin/rm -rf "$STAGE"                 # 旧版没动
  fi
fi
/usr/bin/hdiutil detach "$MNT" >/dev/null 2>&1
/usr/bin/open "$INSTALLED"
"""


def apply_macos(dmg_path: str, installed_app: str, pid: int):
    """挂载 dmg → 校验新 App → 派分离 helper(等本进程退出后替换+重启)。
    返回 (是否已交给 helper, 失败原因)。成功后调用方应尽快退出本进程。"""
    if not os.access(installed_app, os.W_OK):
        return False, "安装目录不可写(可能需手动覆盖)"
    out = subprocess.run(["hdiutil", "attach", "-nobrowse", "-noverify", "-noautoopen", dmg_path],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return False, "挂载 dmg 失败"
    mnt = None
    for line in out.stdout.splitlines():
        cols = line.split("\t")
        if cols and cols[-1].strip().startswith("/Volumes/"):
            mnt = cols[-1].strip()
    if not mnt:
        return False, "找不到挂载点"
    try:
        apps = list(Path(mnt).glob("*.app"))
        if not apps:
            return False, "dmg 内没有 .app"
        new_app = str(apps[0])
        if not verify_macos_app(new_app):
            return False, "新版签名校验未通过，已中止(防篡改)"
        helper = Path(tempfile.gettempdir()) / "voicelog_update_helper.sh"
        helper.write_text(_HELPER, encoding="utf-8")
        helper.chmod(0o755)
        subprocess.Popen(["/bin/bash", str(helper), str(pid), installed_app, new_app, mnt],
                         start_new_session=True)
        return True, ""
    except Exception as e:
        subprocess.run(["hdiutil", "detach", mnt], capture_output=True)
        return False, f"{type(e).__name__}: {e}"


# ============================================================================
#  Windows：跑新 Setup.exe(Inno 自己覆盖)，本进程退出
# ============================================================================
def run_windows_installer(exe_path: str) -> bool:
    try:
        subprocess.Popen([exe_path], close_fds=True)
        return True
    except Exception:
        return False
