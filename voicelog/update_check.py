#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖标准库 urllib/json/re；GitHub Releases API
[OUTPUT]: 对外提供 latest_version()/is_newer()/parse_version()/RELEASES_PAGE/REPO
[POS]: 跨平台「更新提示」中枢，被 voicelog_menubar.py(mac) 与 voicelog_win.py(win) 在后台线程调用。
       只查不装——给提示 + 跳下载页，零签名/重启风险。版本比较是纯函数，便于单测。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

设计哲学：更新检查器只能帮到「已装了它的版本」，所以越早上线越值钱。本模块只负责
  ① 拉一次最新版本号(失败静默，不打扰)  ② 纯函数比大小。装与不装由用户在下载页决定。
"""
import re
import json
import urllib.request

REPO = "zhaozimin/Recorder"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"   # 列出全部:mac/win 用户各取所需


def parse_version(v: str):
    """'v0.9.3' / '0.9.3' / '0.9.3-win-beta' → (0, 9, 3)。取主段前三个数字，忽略后缀。"""
    head = (v or "").strip().lstrip("vV").split("-")[0]
    nums = [int(n) for n in re.findall(r"\d+", head)[:3]]
    return tuple(nums) if nums else (0,)


def is_newer(latest: str, current: str) -> bool:
    """latest 是否严格新于 current（按数字元组比较，长度不齐补零）。"""
    a, b = parse_version(latest), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def latest_version(timeout: float = 8.0) -> str | None:
    """查 GitHub 最新正式 release 的 tag(去 v 前缀)；任何失败都静默返回 None，绝不打扰用户。"""
    try:
        req = urllib.request.Request(
            API_LATEST,
            headers={"User-Agent": "VoiceLog", "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            tag = (json.load(r).get("tag_name") or "").strip()
        return tag.lstrip("vV") or None
    except Exception:
        return None
