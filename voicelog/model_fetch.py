#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖标准库 time/urllib/zipfile/shutil/tempfile;模型 zip 托管在本项目 GitHub Release
[OUTPUT]: 对外提供 model_ready / model_status_key / download_model / get_model_url / MAC_MODEL_URL / WIN_MODEL_URL / model_hint
[POS]: 跨平台「模型获取」中枢,被 voicelog_menubar.py(mac) 与 voicelog_win.py(win) 共用。
       不走 HuggingFace/镜像(国内不稳)——直接从我们自己的 GitHub Release 拉 zip,我可控、国内可达、可手动下。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

设计哲学:把「模型在哪、怎么来」收敛到一处。三种到手方式统一收口——
  ① 已存在本地(用户下过/离线版内置) → 直接用,不重下
  ② 缺失 → 从 GitHub Release 下载 zip,**自带重试的断点续传**(慢/抖网络一次点击磨到下满),同盘原子解压
  ③ 下不动 → 调用方给清晰指引(手动下 zip + 放进文件夹)
"""
import time
import shutil
import tempfile
import zipfile
import urllib.error
import urllib.request
from pathlib import Path

# 模型托管位置:本项目 GitHub Release 的 `models` tag(我可控、国内可达、可续传/手动下)
GITHUB_MODELS_BASE = "https://github.com/zhaozimin/Recorder/releases/download/models"
MAC_MODEL_URL = GITHUB_MODELS_BASE + "/whisper-mlx-turbo.zip"   # macOS / MLX
WIN_MODEL_URL = GITHUB_MODELS_BASE + "/whisper-ct2-turbo.zip"   # Windows / faster-whisper(CT2)

# 四档模型(tiny/base/small/turbo)统一命名:whisper-{mlx|ct2}-{id}.zip,托管同一 models Release。
MODEL_IDS = ("tiny", "base", "small", "turbo")


def get_model_url(model_id: str, platform: str = "mac") -> str:
    """按档位 id 取下载 URL。platform: mac→MLX(Apple Silicon) / win→CT2。"""
    eng = "mlx" if platform == "mac" else "ct2"
    return f"{GITHUB_MODELS_BASE}/whisper-{eng}-{model_id}.zip"


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


# ---------------------------------------------------------------------------
#  下载调参:为「慢且频繁中断」的网络而生——重试不靠次数靠「有无进展」+ 累计字节兜底。
# ---------------------------------------------------------------------------
_CHUNK = 1 << 20          # 1MB/块
_SOCK_TIMEOUT = 60        # 单次 socket 连/读超时(秒):卡死的半开连接及时报错,交由外层续传
_MAX_STALLS = 10          # 连续「零进展」上限:有字节进来就清零,故只有真死网/失效 URL 才会触顶
_BACKOFF_MAX = 30         # 退避上限(秒):第 n 次零进展等 min(2n, 30)s 再续
_MIN_NAP = 1.0            # 有进展也至少歇 1s:杜绝「滴几字节就断」的热循环(真下载分块大,这点延迟可忽略)
_WASTE_FACTOR = 2.5      # 累计下载字节 > 总大小×此值 → 服务器病态(反复重下/不honor Range),放弃
_ABS_CAP = 4 << 30       # total 未知时累计下载绝对上限(4GB),兜底防不终止


class _Cancelled(Exception):
    """用户中途取消下载——与网络异常区分,不留 .part 续传语义之外的副作用。"""


def _nap(secs: float, should_cancel) -> bool:
    """退避小睡:碎成 0.5s 一段,每段看一次取消——死网 30s 退避里也能秒停。被取消返回 True。"""
    for _ in range(int(secs / 0.5) or 1):
        if should_cancel and should_cancel():
            return True
        time.sleep(0.5)
    return False


def _parse_total(content_range) -> int:
    """从 'bytes start-end/total' 抽权威总大小;缺失/未知(*)返回 0。"""
    if not content_range or "/" not in content_range:
        return 0
    tail = content_range.rsplit("/", 1)[-1].strip()
    return int(tail) if tail.isdigit() else 0


def _fetch_to_part(url: str, part: Path, progress_cb, should_cancel, info: dict) -> bool:
    """续一段:从 part 现有大小起带 Range 流式追加。返回 True=读到「干净结尾」(本段无异常流完)。
    总大小(优先 Content-Range 的权威 /total,而非可能只描述本切片的 Content-Length)与本段已读字节
    写进 info——前者防末段中断丢 total、防代理只回切片却被当下完;后者供外层累计字节兜底。
    网络异常向上抛,由外层重试循环裁决续/弃。HTTP 416(Range 越界)= .part 已达完整大小 → 当读完。"""
    have = part.stat().st_size if part.exists() else 0
    headers = {"User-Agent": "VoiceLog"}
    if have:
        headers["Range"] = f"bytes={have}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        resp = urllib.request.urlopen(req, timeout=_SOCK_TIMEOUT)
    except urllib.error.HTTPError as e:
        if e.code == 416:                        # Range 越界:已下满 → 当读完
            return True
        raise
    nread = 0
    with resp as r:
        clen = int(r.headers.get("Content-Length") or 0)
        if getattr(r, "status", 200) == 206:     # 服务器接受续传:追加写
            # 权威总大小取自 Content-Range 的 /total(代理可能只回一段切片却谎报 CL → 否则被当下完)
            auth = _parse_total(r.headers.get("Content-Range"))
            total, done, mode = (auth or have + clen), have, "ab"
            if auth and auth > have + clen:      # 服务器明示:这只是大文件的一段切片(非截断)→ 干净读完该段后应继续下一段
                info["partial"] = True
        else:                                    # 不支持续传(200):从头来,清掉旧残片
            total, done, mode = clen, 0, "wb"
        if total:
            info["total"] = total                # 一拿到头就记总大小(关键:防末段中断丢 total)
        try:
            with open(part, mode) as f:
                while True:
                    if should_cancel and should_cancel():
                        raise _Cancelled()
                    chunk = r.read(_CHUNK)
                    if not chunk:
                        break
                    f.write(chunk)
                    nread += len(chunk)
                    done += len(chunk)
                    if progress_cb and total:
                        progress_cb(min(1.0, done / total))
        finally:
            info["read"] = nread                 # 含中断前已读(累计字节兜底需要)
    return True                                  # 内层循环靠 read()空 自然退出 = 干净结尾


def _finalize(part: Path, dest: Path, should_cancel=None) -> bool:
    """下满后:同盘解压 → 校验权重 → 原子改名落地。zip 损坏(坏续传)→ 弃 part 下次从头,不死循环。
    解压目录与 dest 同盘 → shutil.move 是 rename 而非跨盘拷贝(外置盘场景省一份 1.5G 拷贝)。
    解压前/落地前各看一次取消:落地前停=不安装、留 part;一旦 move 完成即装好,迟来的取消不再回退。"""
    if should_cancel and should_cancel():
        return False                             # 落地前取消:不解压、留 part(未安装)
    ext = dest.parent / (dest.name + ".extract")
    shutil.rmtree(ext, ignore_errors=True)
    ext.mkdir(parents=True, exist_ok=True)
    try:
        try:
            with zipfile.ZipFile(part) as z:
                z.extractall(ext)
        except zipfile.BadZipFile:
            part.unlink(missing_ok=True)         # 续传拼出的 zip 坏了:丢弃,下次重下(不卡死在坏档)
            return False
        src = _find_model_root(ext)
        if not model_ready(src):
            return False
        if should_cancel and should_cancel():
            return False                         # 解压后、落地前取消:不安装,留 part 下次续
        if dest.exists():
            shutil.rmtree(dest, ignore_errors=True)
        shutil.move(str(src), str(dest))
        ok = model_ready(dest)
        if ok:
            part.unlink(missing_ok=True)         # 唯有成功落地才删 part
        return ok
    finally:
        shutil.rmtree(ext, ignore_errors=True)


def download_model(url: str, dest_dir, progress_cb=None, should_cancel=None, status=None) -> bool:
    """下载模型 zip → 解压 → 原子替换 dest_dir。成功返回 True。
    **自带重试的断点续传**:为「慢且频繁中断」的网络而生——点一次就走开,它自己扛。
      · 断了从 .part 的精确字节用 Range 续(GitHub CDN 实测支持 206),不从 0 来;
      · 有进展就清失速计数(慢但在动可无限续),且每次断后都至少歇 _MIN_NAP——杜绝热循环空转;
      · 连续 _MAX_STALLS 次零进展、或累计下载超应有体积太多(病态服务器)→ 放弃,绝不无限循环;
      · .part 放 dest 同盘(非系统临时区),不被 macOS 清理、落地不跨盘拷贝;
      · should_cancel() 返回真即停(留 .part 供下次续);status(可选 dict)回填 'ok'/'cancelled'/'fail'。
    任何异常都吞掉返回 False(留 .part 下次续/调用方给手动指引),绝不把程序拖崩。"""
    def report(s):
        if status is not None:
            status["state"] = s

    dest = Path(dest_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.parent / (dest.name + ".part.zip")   # 稳定位置:同盘、不被清、落地即改名
    total = 0
    stalls = 0
    fetched = 0                                       # 累计从网络读到的字节(含重下浪费)→ 病态兜底
    # —— 重试-续传循环:断一次就从断点自动接着下,直到读到干净结尾/下满,或触顶放弃 ——
    while True:
        if should_cancel and should_cancel():
            report("cancelled"); return False
        cur = part.stat().st_size if part.exists() else 0
        if total and cur >= total:
            break                                    # 字节齐,去解压落地
        info = {}
        eof = False
        try:
            eof = _fetch_to_part(url, part, progress_cb, should_cancel, info)
        except _Cancelled:
            report("cancelled"); return False        # 用户取消:留 part,不算失败也不重试
        except Exception:
            pass                                     # 网络抖动(读到一半抛):据「进展」决定续/弃
        if info.get("total"):
            total = info["total"]
        fetched += info.get("read", 0)
        after = part.stat().st_size if part.exists() else 0
        if total:
            if after >= total:
                break                                # 下满 → 落地
            if eof and not info.get("partial"):      # 干净 EOF 没到 total 且非合法切片 = 截断/谎报;
                report("fail"); return False         # 真断网是异常而非干净EOF,故直接判失败,不空转
            # eof+partial(代理分片):不 break 不 fail,落到下方续传逻辑请求下一段
        elif eof:
            break                                    # 无 Content-Length:干净 EOF 即视为下完(交 finalize 验真)
        # 病态防线:累计下载超绝对上限(最大模型 1.5G,4G 已极宽松)→ 服务器反复重下/谎报,放弃,防不终止
        if fetched > _ABS_CAP or (total and fetched > total * _WASTE_FACTOR):
            report("fail"); return False
        # —— 异常中断:有进展也至少歇 _MIN_NAP(杜绝热循环);零进展则累计失速、指数退避 ——
        if after > cur:
            stalls = 0
            if _nap(_MIN_NAP, should_cancel):
                report("cancelled"); return False
        else:
            stalls += 1
            if stalls >= _MAX_STALLS:                # 连续零进展 → 网真死/URL 失效:放弃(留 part 下次续)
                report("fail"); return False
            if _nap(min(2 * stalls, _BACKOFF_MAX), should_cancel):
                report("cancelled"); return False    # 退避期间被取消
    # —— 下满 → 落地(解压期可取消)——
    if should_cancel and should_cancel():
        report("cancelled"); return False
    ok = _finalize(part, dest, should_cancel)
    if not ok and should_cancel and should_cancel():
        report("cancelled"); return False            # finalize 期间被取消(未安装)
    report("ok" if ok else "fail")
    return ok


def model_hint(url: str, dest_dir) -> str:
    """下载失败时给用户的手动指引(中文)。"""
    return (f"自动下载失败。请手动下载模型：\n\n"
            f"1. 用浏览器打开（国内可访问）：\n   {url}\n"
            f"2. 解压后，把里面的文件夹放到：\n   {dest_dir}\n"
            f"3. 重新打开本应用即可。\n\n"
            f"（或下载「全离线版」安装包，内置模型，无需此步。）")
