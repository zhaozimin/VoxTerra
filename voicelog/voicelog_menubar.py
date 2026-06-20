#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VoiceLog · macOS 菜单栏实时语音日志

[INPUT]: 依赖 sounddevice(采集)、silero_vad(切句)、mlx_whisper(转写)、rumps(菜单栏)、
         speaker.SpeakerGate(声纹门控)；读 config.yaml 全部参数
[OUTPUT]: 可执行入口 VoiceLogApp；幻觉/复读过滤 is_junk、能量门 _rms_dbfs、专名纠错 apply_replace
[POS]: voicelog 的主程序与唯一进程；speaker.py 是它的声纹子模块
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

流程：DJI Mic Mini → sounddevice 实时采集 → Silero VAD 按句切
      → ① 时长门(太短=噪声尖峰) → ② 能量/近场门(太远=外放视频) → ③ 声纹门(不是机主=丢)
      → mlx-whisper(本地 large-v3) 转写 → 复读/幻觉过滤 + 术语纠错
      → 按配置时区写入当天笔记（外置盘掉线自动回退内置盘）
特点：音频转写后立即丢弃，绝不写盘；菜单栏小图标常驻，无 Dock、不抢前台。
配置见 config.yaml：模型/设备/时区/术语偏置/纠错表/掉线回退/三道门控阈值。
"""
import os
import re
import sys
import time
import zlib
import queue
import tempfile
import threading
import datetime
import subprocess
import traceback
from collections import deque
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import sounddevice as sd
import yaml
import rumps
# 关掉会在国内卡死的 hf_xet(ECAPA 声纹模型若走 HF;whisper 模型改走 GitHub,见 model_fetch)
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
import mlx_whisper
from silero_vad import load_silero_vad, VADIterator

from speaker import SpeakerGate
from model_fetch import model_ready, model_status_key, download_model, MAC_MODEL_URL, model_hint
import update_check
import auto_update
import i18n

# ---------------- 路径：只读资源(RES) 与 可写用户数据(DATA) 解耦 ----------------
# 铁律：.app 一旦签名公证，Contents/ 即只读，往里写=毁签名=Gatekeeper 拒运行。
# 故配置/日志/声纹必须落在用户可写区。两种形态：
#   · 打包(.app)：资源在 bundle(_MEIPASS)，数据在 ~/Library/Application Support/VoiceLog
#   · 源码(开发)：资源与数据都在代码旁——保持旧行为，现有 launchd 部署零改动
VERSION = "0.9.3"

FROZEN = getattr(sys, "frozen", False)
RES = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent
DATA = (Path.home() / "Library" / "Application Support" / "VoiceLog") if FROZEN else RES
DATA.mkdir(parents=True, exist_ok=True)

ICON_PATH = RES / "assets" / "menubar.png"   # 菜单栏模板图(原 logo 抠图，只读资源)
CONFIG_PATH = DATA / "config.yaml"           # 唯一可写配置(单一真相源)

# 首次运行(打包版)：把内置默认配置播种到用户区；此后用户的每次修改都写这一份。
if not CONFIG_PATH.exists():
    seed = RES / "config.example.yaml"
    if seed.exists():
        CONFIG_PATH.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")

CFG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
CFG = CFG or {}

SR = 16000
BLOCK = 512  # Silero v5 在 16k 采样率下要求每块正好 512 个采样
MODEL = CFG.get("model", "mlx-community/whisper-large-v3-turbo")
# 模型来源:config 写 "auto"(打包默认)→ 本程序托管,放 DATA/models,缺失则从 GitHub 下载(国内可达);
# 写 HF repo 名或本地路径 → 直接用(开发/进阶,行为不变)。
MANAGED_MODEL = str(MODEL).strip().lower() == "auto"
MODEL_LOCAL = DATA / "models" / "whisper-mlx-turbo"      # 普通版:下载到这里
MODEL_BUNDLED = RES / "models" / "whisper-mlx-turbo"     # 离线版:模型已打进 bundle
if MANAGED_MODEL:
    # 离线版(bundle 内有模型)直接用,否则用下载目录——同一份代码两种形态,零分支差异
    MODEL = str(MODEL_BUNDLED) if model_ready(MODEL_BUNDLED) else str(MODEL_LOCAL)
MAX_UTT_SEC = float(CFG.get("max_utterance_sec", 30))
MIN_SILENCE_MS = int(CFG.get("min_silence_ms", 700))
INPUT_DEVICE = CFG.get("input_device", None)  # None=系统默认；可填编号或名字片段(如 "DJI")
VAULT = Path(os.path.expanduser(CFG.get("vault_path") or "~/VoiceLog/声音日志"))
FALLBACK = Path(os.path.expanduser(CFG.get("fallback_path", "~/voicelog-fallback")))
REPLACE = CFG.get("replace") or {}
INITIAL_PROMPT = CFG.get("initial_prompt", "以下是简体中文普通话的日常口语记录。") or None
TERMS = list(CFG.get("terms") or [])  # 识别词库：单写的目标词，注入 prompt 从源头偏置识别(零误伤)
PREROLL = 8  # 句首预留约 0.25s，避免吃掉第一个字
# 设备掉线自愈：回调持续喂帧=麦还活着。超过这么久没有任何回调=设备掉线/默认设备被切走，
# 主动抛出交给看门狗重开流——不能依赖 sounddevice 抛异常(CoreAudio 掉线时它只是静默停摆)。
NO_AUDIO_TIMEOUT_SEC = float(CFG.get("no_audio_timeout_sec", 5))

# ---------------- 三道门控参数（治「没说话却冒字」「外放视频被记成你」） ----------------
# ① VAD 进入阈值：默认 0.5 对贴身领夹麦太松，底噪/呼吸/衣物摩擦的单帧尖峰就能开句。0.6~0.7 更稳。
VAD_THRESHOLD = float(CFG.get("vad_threshold", 0.6))
# ② 最短句长：VADIterator 本身无此门槛，单个 32ms 噪声帧即开句 → 这里补上，太短直接判噪声丢弃。
MIN_SPEECH_MS = int(CFG.get("min_speech_ms", 300))
# ③ 能量/近场门：贴身麦上「你的声音」又响又干，远处外放又轻又混响。低于此响度判远场，丢弃。
ENERGY_GATE = bool(CFG.get("energy_gate", True))
MIN_RMS_DBFS = float(CFG.get("min_rms_dbfs", -45.0))  # 需按你的麦增益校准（见 config 注释）
# ④ 声纹门：注册机主音色后，逐句算余弦相似度，不像你就丢。注册前自动放行(fail-open)。
SPEAKER_GATE = bool(CFG.get("speaker_gate", False))
SPEAKER_THRESHOLD = float(CFG.get("speaker_threshold", 0.35))  # 偏放行；按菜单显示的「上句相似度」校准
SPEAKER_PROFILE = CFG.get("speaker_profile", "~/voicelog-models/speaker_profile.npy")
ENROLL_SCRIPT = CFG.get("enroll_script") or None  # 自定义朗读稿；留空用内置日常口语
ENROLL_INTRO = CFG.get("enroll_intro") or None    # 自定义注册须知/广告词；留空用内置文案
# 质量驱动注册：不再按固定秒数"盲采"(用户发呆就采到一堆静音)，改为累计「有效语音」秒数，采够才停。
ENROLL_VOICED_SEC = float(CFG.get("enroll_voiced_sec", 20))     # 目标:采够这么多秒有效语音=完成
ENROLL_MAX_SEC = float(CFG.get("enroll_max_sec", 120))          # 硬上限:一直没声音时兜底，防止无限等
ENROLL_VOICE_FLOOR = float(CFG.get("enroll_voice_floor_dbfs", -40.0))  # 高于此响度的帧才算"在朗读"
ENROLL_QUALITY_OK = float(CFG.get("enroll_quality_ok", 0.60))   # 提取质量低于此提示重采

# 注册朗读稿/须知 + 全部 UI 文案现由 i18n 按当前语言提供(见 i18n.py)；config 可用 enroll_script/enroll_intro 覆盖。
i18n.set_language(CFG.get("ui_language") or "")        # 界面语言(UI)；""=跟随系统
i18n.set_primary(CFG.get("primary_language") or "")    # 主语言=转写语言；""=跟随系统
i18n.set_secondary(CFG.get("secondary_language") or "")  # 辅语言=日常夹杂语言；""=无


def log_dir() -> Path:
    d = DATA / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_err(msg: str) -> None:
    try:
        with (log_dir() / "err.log").open("a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.datetime.now()}] {msg}")
    except Exception:
        pass


# ---------------- 时区 ----------------
# timezone 留空 = 跟随系统本地（macOS 开了自动时区，人飞到哪就记哪的时间）；
# 或填 IANA 名（"Asia/Shanghai" / "America/New_York" / "Europe/London"）钉死某个时区。
try:
    _TZ = ZoneInfo(CFG["timezone"]) if CFG.get("timezone") else None
except Exception:
    append_err(f"无效时区 {CFG.get('timezone')!r}，改用系统本地")
    _TZ = None


def now() -> datetime.datetime:
    """统一的“现在”：决定时间戳与当天笔记的归属日。跨时区出差时由 config.timezone 控制。"""
    return datetime.datetime.now(_TZ)


# 菜单栏「时区」子菜单里列出的快捷选项（空串=跟随系统本地）；可在 config.timezone_choices 自定义
TZ_CHOICES = CFG.get("timezone_choices") or [
    "", "Asia/Shanghai", "Asia/Tokyo", "Asia/Singapore",
    "Europe/London", "America/New_York", "America/Los_Angeles",
]


def set_timezone(tz: str) -> bool:
    """运行时切换时区：改全局 _TZ（立即影响后续 now()）并写回 config.yaml（重启也记住）。"""
    global _TZ
    try:
        _TZ = ZoneInfo(tz) if tz else None
    except Exception:
        append_err(f"切换时区失败：{tz!r}")
        return False
    try:  # 只替换 timezone 那一行，保留文件里其余注释
        cfg = CONFIG_PATH
        text = cfg.read_text(encoding="utf-8")
        new = re.sub(r"(?m)^timezone:.*$", f'timezone: "{tz}"', text)
        if new != text:
            cfg.write_text(new, encoding="utf-8")
    except Exception:
        append_err("写回时区失败：" + traceback.format_exc().splitlines()[-1])
    return True


# ---------------- 输出目录（运行时可改） ----------------
def choose_folder():
    """弹原生「选择文件夹」对话框，返回所选目录绝对路径；取消/失败返回 None。"""
    script = 'POSIX path of (choose folder with prompt "选择语音日志保存文件夹")'
    try:
        r = subprocess.run(["osascript", "-e", script],
                           capture_output=True, text=True, timeout=120)
        return r.stdout.strip() or None
    except Exception:
        append_err("choose_folder: " + traceback.format_exc().splitlines()[-1])
        return None


def set_vault(path: str) -> bool:
    """运行时切换输出目录：改全局 VAULT（立即影响后续写入）并写回 config.yaml。"""
    global VAULT
    try:
        v = Path(os.path.expanduser(path))
        v.mkdir(parents=True, exist_ok=True)
        VAULT = v
    except Exception:
        append_err(f"设置保存目录失败：{path!r}")
        return False
    try:  # 只替换 vault_path 那一行，保留注释
        cfg = CONFIG_PATH
        text = cfg.read_text(encoding="utf-8")
        new = re.sub(r"(?m)^vault_path:.*$", f'vault_path: "{path}"', text)
        if new != text:
            cfg.write_text(new, encoding="utf-8")
    except Exception:
        append_err("写回 vault_path 失败：" + traceback.format_exc().splitlines()[-1])
    return True


def set_config_flag(key: str, value: bool) -> None:
    """把 config.yaml 里某布尔开关写成 true/false（保留注释），用于持久化菜单栏的运行时切换。"""
    try:
        cfg = CONFIG_PATH
        text = cfg.read_text(encoding="utf-8")
        new = re.sub(rf"(?m)^{re.escape(key)}:.*$",
                     f"{key}: {'true' if value else 'false'}", text)
        if new != text:
            cfg.write_text(new, encoding="utf-8")
    except Exception:
        append_err(f"写回 {key} 失败：" + traceback.format_exc().splitlines()[-1])


def set_config_str(key: str, value: str) -> None:
    """把 config.yaml 里某个字符串项写成 key: "value"（不存在则追加），用于持久化语言等运行时选择。"""
    try:
        cfg = CONFIG_PATH
        text = cfg.read_text(encoding="utf-8")
        line = f'{key}: "{value}"'
        pat = re.compile(rf"(?m)^{re.escape(key)}:.*$")
        new = pat.sub(line, text) if pat.search(text) else text.rstrip() + "\n" + line + "\n"
        cfg.write_text(new, encoding="utf-8")
    except Exception:
        append_err(f"写回 {key} 失败：" + traceback.format_exc().splitlines()[-1])


def resolve_device(dev):
    """把 config 里的 input_device 解析成 sounddevice 能用的编号/None。"""
    if dev is None or dev == "":
        return None
    try:
        return int(dev)  # 直接是编号
    except (ValueError, TypeError):
        pass
    for i, d in enumerate(sd.query_devices()):  # 按名字片段匹配
        if d.get("max_input_channels", 0) > 0 and str(dev).lower() in d["name"].lower():
            return i
    append_err(f"未找到匹配输入设备：{dev}，改用系统默认")
    return None


# ---------------- 幻觉过滤 ----------------
# whisper 在静音/噪声上有两种幻觉：(1) 吐训练集字幕水印(“谢谢观看”)，(2) 锁进复读循环(“慢慢慢…”)。
# 实测 no_speech_prob 恒为 0、avg_logprob 还很高，概率信号根本识别不了，compression_ratio 只触发升温
# 重试不丢弃 —— 唯一可靠的办法是：上游门控让噪声压根别进 whisper(时长/能量/声纹) + 下游双层文本过滤
# (字幕水印黑名单 + 结构性复读检测)。
_HALLUCINATIONS = {
    "优优独播剧场YoYo Television Series Exclusive",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目",
    "明镜与点点栏目",
    "字幕由Amara.org社区提供",
    "本字幕由观众提供",
    "请订阅我的频道",
    "谢谢观看",
    "谢谢大家",
    "下集再见",
}


def _norm(s: str) -> str:
    """归一化用于幻觉比对：只留字母数字汉字、转小写，抹掉空白与标点的差异。"""
    return "".join(ch.lower() for ch in s if ch.isalnum())


# 短套话（<8 归一字符）只做整句精确匹配，避免误杀真说的“谢谢大家…”；
# 长水印做子串匹配，容忍 whisper 前后多带的标点/空白。
_DROP_EXACT = {_norm(s) for s in _HALLUCINATIONS | set(CFG.get("drop_phrases") or [])}
_DROP_SUB = {d for d in _DROP_EXACT if len(d) >= 8}


def _looped(text: str) -> bool:
    """复读循环检测：whisper 在噪声/近静音上会锁进单 token 自我复读（「慢慢慢…」或整句复读
    几十遍）。这是开放式的新内容，固定黑名单结构上抓不住 —— 必须看「文本自身的结构」：
      · 8+ 连续同字              → 单字复读(幻觉是几十上百连排；阈值留到 8 以放过「慢慢慢慢慢」这种正常强调)
      · 字符多样性崩塌(<0.25)    → 少数字反复出现
      · 长文本 zlib 压缩比 >3.0  → 整句复读高度可压(自然中文约 1.5~2.5，留足余量)
    """
    n = _norm(text)
    if not n:
        return False
    if re.search(r"(.)\1{7,}", n):
        return True
    if len(n) >= 12 and len(set(n)) / len(n) < 0.25:
        return True
    if len(n) >= 30:
        b = n.encode("utf-8")
        if len(b) / max(1, len(zlib.compress(b))) > 3.0:
            return True
    return False


def is_junk(text: str) -> bool:
    n = _norm(text)
    if not n:
        return False
    return _looped(text) or n in _DROP_EXACT or any(d in n for d in _DROP_SUB)


def _rms_dbfs(x: np.ndarray) -> float:
    """段平均响度(dBFS)。贴身麦近场说话约 -25~-12，远处外放/底噪低得多 → 近场门的判据。"""
    rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    return 20.0 * np.log10(rms + 1e-9)


def apply_replace(text: str) -> str:
    """专名纠错。ASCII 词用词边界匹配，避免 Cloud→Claude 误伤 iCloud/Cloudflare 等更大的英文词。"""
    for k, v in REPLACE.items():
        if k.isascii() and k.strip():
            text = re.sub(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", v, text)
        else:
            text = text.replace(k, v)
    return text


def current_prompt():
    """实际喂给 whisper 的 initial_prompt = 当前语言的基础提示 + 识别词库(TERMS)。
    zh 优先用 config 的 initial_prompt(含用户惯用术语)；其他语言用 i18n 默认提示。词库从源头偏置，零误伤。"""
    base = INITIAL_PROMPT if (i18n.primary() == "zh" and INITIAL_PROMPT) else i18n.prompt()
    if TERMS:
        base = (base + i18n.t("prompt_terms", terms="、".join(TERMS))).strip()
    return base or None


# ---------------- 关键词管理：文本 <-> (纠错表 rules, 识别词库 terms) <-> config 同步 ----------------
# 窗口里每行一条：含 `=` → 精确纠错(rules)；不含 `=` → 识别词库(terms，注入 prompt)。
def corrections_to_text(rules: dict, terms: list) -> str:
    """(rules, terms) → 逐行文本，喂给关键词窗口编辑。"""
    return "\n".join([f"{k} = {v}" for k, v in rules.items()] + list(terms))


def parse_corrections(text: str):
    """逐行文本 → (rules, terms)：含 `=` 入 rules(首个=分隔)，否则入 terms；忽略空行与 # 注释，terms 去重。"""
    rules, terms = {}, []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip():
                rules[k.strip()] = v.strip()
        elif line not in terms:
            terms.append(line)
    return rules, terms


def _yq(s: str) -> str:
    """YAML 双引号转义：含中文/空格/特殊字符的键值写回 config 才安全。"""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _write_block(key: str, body: str) -> None:
    """把 config.yaml 里某个顶层块(key: ...)整体替换为 body，保留其余内容；不存在则追加到文件尾。"""
    try:
        cfg = CONFIG_PATH
        text = cfg.read_text(encoding="utf-8")
        # key 块到「下个顶层键 / 空行 / 文件尾」为止——遇空行即停，保留段间分隔，保证幂等。
        pat = re.compile(rf"(?ms)^{re.escape(key)}:.*?(?=^[^\s#]|^[ \t]*$|\Z)")
        new = pat.sub(lambda m: body, text) if pat.search(text) else text.rstrip() + "\n\n" + body
        cfg.write_text(new, encoding="utf-8")
    except Exception:
        append_err(f"_write_block {key}: " + traceback.format_exc().splitlines()[-1])


def write_corrections(rules: dict, terms: list) -> None:
    """更新纠错表+识别词库：① 立即生效(改全局 REPLACE/TERMS，下句转写即用) ② 写回 config.yaml 两个块。"""
    REPLACE.clear()
    REPLACE.update(rules)
    TERMS[:] = terms
    rblock = ("replace: {}\n" if not rules else
              "replace:\n" + "".join(f"  {_yq(k)}: {_yq(v)}\n" for k, v in rules.items()))
    tblock = ("terms: []\n" if not terms else
              "terms:\n" + "".join(f"  - {_yq(t)}\n" for t in terms))
    _write_block("replace", rblock)
    _write_block("terms", tblock)


# ---------------- 写入（外置盘掉线自动回退内置盘，绝不丢字） ----------------
def _ext_mount(p: Path):
    """p 若在外置卷 /Volumes/X 下，返回挂载点 /Volumes/X；内置路径返回 None。"""
    parts = p.parts
    return Path("/Volumes") / parts[2] if len(parts) >= 3 and parts[1] == "Volumes" else None


def _usable(base: Path) -> bool:
    """外置卷必须真的挂载着才算可用 —— 否则会在 /Volumes 下建幽灵目录并静默丢数据。"""
    m = _ext_mount(base)
    return m is None or m.is_mount()


def write_line(text: str) -> str:
    """把一行写进当天笔记；首选 vault，外置盘不可用时回退内置盘。返回实际落点标记。"""
    ts = now()
    line = f"- **{ts:%H:%M}** {text}\n"
    for base, tag in ((VAULT, "vault"), (FALLBACK, "fallback")):
        if not _usable(base):
            continue
        try:
            note = base / f"{ts:%Y-%m-%d}.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            if not note.exists():
                note.write_text(f"# {ts:%Y-%m-%d} 语音日志\n\n", encoding="utf-8")
            with note.open("a", encoding="utf-8") as f:
                f.write(line)
            return tag
        except Exception:
            append_err(f"写入 {base} 失败: " + traceback.format_exc().splitlines()[-1])
    return "lost"


# ---------------- 录音 + 转写线程 ----------------
class Recorder(threading.Thread):
    def __init__(self, state: dict):
        super().__init__(daemon=True)
        self.state = state
        self.q: queue.Queue = queue.Queue()
        self.muted = False
        self.vad = load_silero_vad()
        self.device = None                       # 每次开流时按 config 重新解析(见 _stream_loop)
        self._last_audio = time.monotonic()      # 回调心跳：麦最后一次喂帧的时刻(掉线自愈用)
        self.speaker = SpeakerGate(SPEAKER_PROFILE, SPEAKER_THRESHOLD)
        self.speaker_on = SPEAKER_GATE  # 运行时可切换；注册后无需重启即可开启
        self._enroll = None  # 注册采集缓冲：None=未注册中；list=正在旁路收集机主语音
        self._enroll_cancel = False

    def _callback(self, indata, frames, time_info, status):
        self._last_audio = time.monotonic()  # 心跳：只要回调被调用就说明麦还在喂帧(早于静音/注册判断)
        if status:
            self.state["status"] = str(status)
        mono = indata[:, 0].copy()           # 取单声道，拷贝出回调缓冲
        buf = self._enroll                   # 快照引用：worker 随时可能把它置 None，避免 None.append 竞争
        if buf is not None:
            buf.append(mono)                  # 注册期间：只旁路采集，不喂转写流(否则朗读稿会进日志)
            return
        if not self.muted:
            self.q.put(mono)

    def run(self):
        while True:
            try:
                self._stream_loop()
            except Exception:
                self.state["err"] = traceback.format_exc().splitlines()[-1]
                append_err(traceback.format_exc())
                sd.sleep(3000)  # 设备掉线/出错 → 等 3 秒重连

    def _stream_loop(self):
        self.device = resolve_device(INPUT_DEVICE)  # 每次(重)开按名字片段重解析：设备拔插后编号会变
        vad_iter = VADIterator(
            self.vad, threshold=VAD_THRESHOLD, sampling_rate=SR,
            min_silence_duration_ms=MIN_SILENCE_MS, speech_pad_ms=100,
        )
        preroll = deque(maxlen=PREROLL)
        buf, triggered = [], False
        self.state["err"] = ""
        with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                            blocksize=BLOCK, device=self.device,
                            callback=self._callback):
            self.state["live"] = True
            self._last_audio = time.monotonic()  # 刚开流即刷新心跳，避免被上一段静默误判掉线
            while True:
                try:
                    x = self.q.get(timeout=1.0)
                except queue.Empty:
                    # 队列空≠掉线：可能只是没说话或已静音(muted/注册期回调不入队)。
                    # 用回调心跳辨真假死——回调还在烧=麦活着，继续等；
                    # 回调停摆超阈值=麦掉线/默认设备被切走，主动抛出让 run() 看门狗重开流(会抓回归来的麦)。
                    if time.monotonic() - self._last_audio > NO_AUDIO_TIMEOUT_SEC:
                        self.state["live"] = False
                        raise RuntimeError(f"audio stalled: no frames for {NO_AUDIO_TIMEOUT_SEC:.0f}s")
                    continue
                preroll.append(x)
                flag = vad_iter(x, return_seconds=False)
                if flag and "start" in flag:
                    triggered = True
                    buf = list(preroll)
                elif triggered:
                    buf.append(x)

                end_now = bool(flag and "end" in flag)
                too_long = len(buf) * BLOCK > MAX_UTT_SEC * SR
                if triggered and (end_now or too_long):
                    triggered = False
                    utt = np.concatenate(buf) if buf else None
                    buf = []
                    if too_long and not end_now:
                        vad_iter.reset_states()  # 强制切句后重置，避免漏掉后续语音
                    if utt is not None and self._accept(utt):
                        self._transcribe(utt)

    # ---------------- 转写前的三道门：让噪声/外放/他人压根别进 whisper ----------------
    def _accept(self, utt: np.ndarray) -> bool:
        if utt.size < MIN_SPEECH_MS * SR // 1000:           # ① 时长门：太短 = 噪声尖峰
            return self._drop("short")
        if ENERGY_GATE and _rms_dbfs(utt) < MIN_RMS_DBFS:   # ② 能量门：太远 = 外放视频/底噪
            return self._drop("far")
        if self.speaker_on:                                 # ③ 声纹门：不是机主
            ok, score = self.speaker.verify(utt)
            self.state["last_score"] = round(score, 3)
            if not ok:
                return self._drop("speaker")
        return True

    def _drop(self, reason: str) -> bool:
        self.state["dropped"] = self.state.get("dropped", 0) + 1
        self.state["last_drop"] = reason
        return False

    def enroll(self):
        """质量驱动注册：旁路采集，累计「有效语音」秒数(响度过门的帧)，采够 ENROLL_VOICED_SEC 才停。
        用户中途发呆不会让采集失效——只数真正在说话的部分；硬上限 ENROLL_MAX_SEC 兜底。进度写入 state。"""
        self._enroll_cancel = False

        def _run():
            st = self.state
            st.update(enrolling=True, enroll_voiced=0.0, enroll_progress=0.0,
                      enroll_elapsed=0, enroll_quality=None, enroll_ok=False,
                      enroll_cancelled=False)
            self._enroll = []                       # 打开旁路采集（callback 开始喂数据）
            voiced_frames, voiced_sec, elapsed, idx = [], 0.0, 0.0, 0
            while (not self._enroll_cancel and voiced_sec < ENROLL_VOICED_SEC
                   and elapsed < ENROLL_MAX_SEC):
                sd.sleep(200)
                elapsed += 0.2
                frames = self._enroll or []
                for f in frames[idx:]:              # 只数新到的帧里"在朗读"的部分
                    if _rms_dbfs(f) > ENROLL_VOICE_FLOOR:
                        voiced_frames.append(f)
                        voiced_sec += len(f) / SR
                idx = len(frames)
                st["enroll_voiced"] = round(voiced_sec, 1)
                st["enroll_progress"] = min(1.0, voiced_sec / ENROLL_VOICED_SEC)
                st["enroll_elapsed"] = round(elapsed)
            self._enroll = None
            if self._enroll_cancel:
                st.update(enrolling=False, enroll_cancelled=True, enroll_ok=False)
                return
            wav = np.concatenate(voiced_frames) if voiced_frames else np.zeros(0, np.float32)
            st["enroll_ok"] = bool(wav.size) and self.speaker.enroll(wav)  # 只拿有效语音去建质心
            st["enroll_quality"] = self.speaker.last_quality
            st["enrolled"] = self.speaker.enrolled
            st["enrolling"] = False

        threading.Thread(target=_run, daemon=True).start()

    def cancel_enroll(self):
        self._enroll_cancel = True
        self._enroll = None   # 立刻停旁路采集→实时转写当即恢复，不等 worker 下一拍(最多 200ms)

    def _transcribe(self, utt: np.ndarray):
        if MANAGED_MODEL and not model_ready(MODEL):
            self.state["need_model"] = True   # 模型未下载,别硬转(会抛错);菜单提示用户去下
            return
        try:
            result = mlx_whisper.transcribe(
                utt, path_or_hf_repo=MODEL, language=i18n.whisper_lang(),  # 转写语言跟随所选 UI 语言
                initial_prompt=current_prompt(),    # 当前语言基础提示 + 识别词库
                condition_on_previous_text=False,   # 防复读式幻觉滚雪球
            )
            text = (result.get("text") or "").strip()
        except Exception:
            append_err("transcribe: " + traceback.format_exc())
            return
        if not text or is_junk(text):  # 空串 / 字幕水印幻觉 —— 直接丢弃，不污染日志
            return
        text = apply_replace(text)     # 专名纠错（ASCII 词按词边界，安全）

        sink = write_line(text)        # 外置盘掉线会自动回退内置盘
        if sink == "lost":
            return
        self.state["count"] += 1
        self.state["last"] = text
        self.state["sink"] = sink
        # utt 在此返回后即被回收 —— 音频从不落盘


# ---------------- 菜单栏 ----------------
class VoiceLogApp(rumps.App):
    def __init__(self):
        super().__init__("", quit_button=None)   # 标题留空，用自定义图标
        self._request_mic()      # 主动申请麦克风权限——靠 PortAudio 触发弹窗不可靠(无权限时它在查设备阶段就失败)
        self._has_icon = False
        self._setup_icon()
        self.state = {"count": 0, "last": "", "err": "", "live": False,
                      "status": "", "sink": "vault", "dropped": 0,
                      "enrolling": False, "enrolled": False, "last_score": None}
        self.rec = Recorder(self.state)
        self.state["enrolled"] = self.rec.speaker.enrolled
        self.rec.start()
        self._enroll_win = None      # 注册会话三件套：窗口 / 进度定时器 / 结果展示倒数
        self._enroll_timer = None
        self._enroll_close_in = 0
        self._cur_tz = CFG.get("timezone") or ""
        self._cur_lang = CFG.get("ui_language") or ""        # 界面语言
        self._cur_primary = CFG.get("primary_language") or ""    # 主语言=转写语言
        self._cur_secondary = CFG.get("secondary_language") or ""  # 辅语言

        self.count_item = rumps.MenuItem(i18n.t("count", n=0))  # 存引用，标题会变
        self.toggle_item = rumps.MenuItem(i18n.t("pause"), callback=self.toggle)
        codes = list(i18n.LANG_ORDER)                        # ["", zh, en, ja]
        self.ui_lang_menu, self._ui_lang_items = self._lang_menu(
            i18n.t("lang_menu", name=self._disp(self._cur_lang)),
            self._cur_lang, codes, i18n.t("follow_system"), self.pick_lang)
        self.primary_menu, self._primary_items = self._lang_menu(
            i18n.t("primary_menu", name=self._disp(self._cur_primary)),
            self._cur_primary, codes, i18n.t("follow_system"), self.pick_primary)
        self.secondary_menu, self._secondary_items = self._lang_menu(
            i18n.t("secondary_menu", name=self._disp_sec(self._cur_secondary)),
            self._cur_secondary, codes, i18n.t("none"), self.pick_secondary)
        self.tz_menu = self._build_tz_menu()                # 「时区」子菜单
        self.vault_item = rumps.MenuItem(self._vault_title(), callback=self.pick_vault)
        self.enroll_item = rumps.MenuItem(self._enroll_title(), callback=self.do_enroll)
        self.spk_item = rumps.MenuItem(self._spk_title(), callback=self.toggle_speaker)
        self.kw_item = rumps.MenuItem(i18n.t("keywords"), callback=self.do_replace)
        self.note_item = rumps.MenuItem(i18n.t("open_note"), callback=self.open_note)
        self.model_item = rumps.MenuItem(self._model_title(), callback=self.do_model)
        self.quit_item = rumps.MenuItem(i18n.t("quit"), callback=self.quit_app)
        self.version_item = rumps.MenuItem(i18n.t("cur_version", app=i18n.t("app_name"), v=VERSION))  # 无回调=不可点
        self.update_item = rumps.MenuItem(i18n.t("upd_checking"), callback=self.do_update)  # 更新提示/自动更新
        threading.Thread(target=self._check_update, daemon=True).start()        # 启动即后台查新版
        self.ad_item = rumps.MenuItem("作者主页：zhaozimin.cn", callback=self.open_homepage)
        self._style_ad(self.ad_item, "📣 作者主页：zhaozimin.cn", (0.39, 0.58, 0.86))      # 柔和蓝
        self.ad2_item = rumps.MenuItem("Obsidian 资料库：guangtou.me", callback=self.open_vault_site)
        self._style_ad(self.ad2_item, "🪨 Obsidian 资料库：guangtou.me", (0.62, 0.47, 0.82))  # 柔和紫·黑曜石
        self.ad3_item = rumps.MenuItem("GitHub：github.com/zhaozimin", callback=self.open_github)
        self._style_ad(self.ad3_item, "🐱 GitHub：github.com/zhaozimin", (0.90, 0.70, 0.20))  # 柔和黄·Octocat 小猫
        self.menu = [
            self.count_item,
            self.toggle_item,
            None,  # 分隔线
            self.model_item,   # 模型状态常显：🟢已就绪 / ⬇下载 / ⏳下载中 / ⚠️未找到——任何模式都不黑盒
            self.enroll_item,
            self.spk_item,
            None,  # 分隔线
            self.ui_lang_menu,
            self.primary_menu,
            self.secondary_menu,
            self.tz_menu,
            self.vault_item,
            self.kw_item,
            self.note_item,
            None,  # 分隔线
            self.version_item,                       # 版本
            self.update_item,                        # 更新提示（检查中/已最新/有新版）
            self.ad_item,                            # 作者主页（柔和蓝）
            self.ad2_item,                           # Obsidian 资料库（柔和绿）
            self.ad3_item,                           # GitHub（柔和黄）
            self.quit_item,
        ]

    def _setup_icon(self):
        """用 logo 模板图当菜单栏图标(替代 emoji)。rumps 把图标写死 20×20 方形会压扁宽 logo，
        故建好后用 PyObjC 按真实像素宽高比重设尺寸(高约 19pt)。失败则退回 emoji。"""
        try:
            if not ICON_PATH.exists():
                return
            self._template = True               # 模板模式：深/浅菜单栏自动反色
            self.icon = str(ICON_PATH)          # rumps 建 _icon_nsimage(默认 20×20)
            img = self._icon_nsimage
            reps = img.representations() if img is not None else None
            if reps:
                asp = reps[0].pixelsWide() / max(1, reps[0].pixelsHigh())
                img.setSize_((round(19 * asp), 19))   # 保宽高比
            self._has_icon = True
        except Exception:
            append_err("setup_icon: " + traceback.format_exc().splitlines()[-1])

    @staticmethod
    def _vault_title() -> str:
        parts = VAULT.parts
        short = "/".join(parts[-2:]) if len(parts) >= 2 else str(VAULT)
        return i18n.t("vault", p=short)

    def pick_vault(self, _):
        p = choose_folder()
        if not p or not set_vault(p):
            return
        self.vault_item.title = self._vault_title()

    # ---------------- 声纹：注册 + 门控开关 ----------------
    def _enroll_title(self) -> str:
        if self.state.get("enrolling"):
            return i18n.t("enroll_running")
        if self.state.get("enrolled"):
            return "🟢 " + i18n.t("enroll_item", mark=i18n.t("mark_done"))   # 已注册=绿圈
        return i18n.t("enroll_item", mark=i18n.t("mark_todo"))

    def do_enroll(self, _):
        if self.state.get("enrolling") or getattr(self, "_enroll_win", None):
            return  # 已在注册中 / 窗口已开 → 不重复弹
        if not self.rec.speaker.available():
            rumps.alert(i18n.t("spk_unavail_t"), i18n.t("spk_unavail_b"))
            return
        intro = ENROLL_INTRO or i18n.enroll_intro()
        script = ENROLL_SCRIPT or i18n.enroll_script()
        try:                               # 第一阶段：弹「须知页」，不录音；点开始才进采集
            from enroll_ui import EnrollWindow
            self._enroll_win = EnrollWindow(intro, script,
                                            on_start=self._enroll_start,
                                            on_cancel=self._enroll_cancel)
        except Exception:
            append_err("EnrollWindow: " + traceback.format_exc())
            self._enroll_win = None
            rumps.alert(i18n.t("enroll_fail_t"), i18n.t("enroll_fail_b"))

    def _enroll_start(self):
        """用户点「开始」后才真正录音 + 启动进度刷新定时器。"""
        if self._enroll_timer:           # 先停掉残留定时器，避免孤儿计时器叠加
            self._enroll_timer.stop()
        self._enroll_close_in = 12
        self.rec.enroll()
        self._enroll_timer = rumps.Timer(self._enroll_tick, 0.25)
        self._enroll_timer.start()

    def _enroll_cancel(self):
        """用户点「取消」：停采集与定时器、清引用（窗口自身随后关闭）。"""
        self.rec.cancel_enroll()
        t = getattr(self, "_enroll_timer", None)
        if t:
            t.stop()
        self._enroll_timer = None
        self._enroll_win = None

    def _enroll_tick(self, _):
        st = self.state
        win = getattr(self, "_enroll_win", None)
        if win is None:                # 已取消/收尾 → 停定时器
            t = getattr(self, "_enroll_timer", None)
            if t:
                t.stop()
            return
        if st.get("enrolling"):        # 采集中：刷进度
            win.update(st.get("enroll_progress", 0.0), st.get("enroll_voiced", 0.0),
                       ENROLL_VOICED_SEC, st.get("enroll_elapsed", 0))
            self._enroll_close_in = 12
            return
        if not getattr(win, "_finished", False):  # 刚结束：展示结果
            if st.get("enroll_cancelled"):
                win.finish(False, i18n.t("cancelled"))
            elif st.get("enroll_ok"):
                q = st.get("enroll_quality")
                qp = f"{round(q*100)}%" if isinstance(q, (int, float)) else "—"
                tip = "" if (not isinstance(q, (int, float)) or q >= ENROLL_QUALITY_OK) else i18n.t("quality_low")
                win.finish(True, i18n.t("done", q=qp) + tip)
            else:
                win.finish(False, i18n.t("failed"))
        self._enroll_close_in -= 1
        if self._enroll_close_in <= 0:  # 结果展示 ~3s 后自动收尾
            self._enroll_win = None      # 先断引用 + 停表，再关窗——确保没有 tick 能碰到关掉的窗口
            if self._enroll_timer:
                self._enroll_timer.stop()
                self._enroll_timer = None
            win.close()

    def _spk_title(self) -> str:
        s = self.state.get("last_score")
        # 圈色：关=🔴；开且上句相似度低于阈值(识别度不高)=🟡；开且正常=🟢
        if not self.rec.speaker_on:
            dot = "🔴"
        elif s is not None and s < SPEAKER_THRESHOLD:
            dot = "🟡"
        else:
            dot = "🟢"
        tail = i18n.t("spk_score", s=s) if (self.rec.speaker_on and s is not None) else ""
        state = i18n.t("on") if self.rec.speaker_on else i18n.t("off")
        return f"{dot} " + i18n.t("spk_gate", state=state) + tail

    def toggle_speaker(self, _):
        if not self.rec.speaker.enrolled and not self.rec.speaker_on:
            rumps.alert(i18n.t("need_enroll_t"), i18n.t("need_enroll_b"))
            return
        self.rec.speaker_on = not self.rec.speaker_on
        set_config_flag("speaker_gate", self.rec.speaker_on)
        self.spk_item.title = self._spk_title()

    # ---------------- 关键词管理（纠错 + 识别词库） ----------------
    def do_replace(self, _):
        if self.state.get("enrolling") or self._enroll_win:
            rumps.alert(i18n.t("replace_busy_t"), i18n.t("replace_busy_b"))
            return
        try:
            from replace_ui import ReplaceWindow
            win = ReplaceWindow(corrections_to_text(REPLACE, TERMS))
            result, text = win.run_modal()
        except Exception:
            append_err("ReplaceWindow: " + traceback.format_exc())
            rumps.alert(i18n.t("kw_fail_t"), i18n.t("kw_fail_b"))
            return
        if result != "save":
            return
        rules, terms = parse_corrections(text)
        write_corrections(rules, terms)
        rumps.alert(i18n.t("kw_saved_t"), i18n.t("kw_saved_b", r=len(rules), t=len(terms)))

    @staticmethod
    def _tz_title(tz: str) -> str:
        return i18n.t("tz", tz=tz or i18n.t("follow_system"))

    def _build_tz_menu(self):
        cur = CFG.get("timezone") or ""
        menu = rumps.MenuItem(self._tz_title(cur))
        self._tz_items = {}                       # 时区码 → 菜单项(靠身份判定，不靠标题)
        for tz in TZ_CHOICES:
            label = i18n.t("follow_system") if tz == "" else tz
            item = rumps.MenuItem(label, callback=self.pick_tz)
            item.state = 1 if tz == cur else 0
            menu.add(item)
            self._tz_items[tz] = item
        self._tz_follow = self._tz_items.get("")
        return menu

    def pick_tz(self, sender):
        tz = next((z for z, it in self._tz_items.items() if it is sender), "")
        if not set_timezone(tz):
            return
        self._cur_tz = tz
        for z, it in self._tz_items.items():
            it.state = 1 if z == tz else 0
        self.tz_menu.title = self._tz_title(tz)

    # ---------------- 语言：界面语言 / 主语言(转写) / 辅语言(夹杂) 三者独立 ----------------
    @staticmethod
    def _disp(code):
        return i18n.lang_display(code) if code else i18n.t("follow_system")

    @staticmethod
    def _disp_sec(code):
        return i18n.lang_display(code) if code else i18n.t("none")

    def _lang_menu(self, title, cur, codes, none_label, cb):
        menu = rumps.MenuItem(title)
        items = {}
        for code in codes:
            label = none_label if code == "" else i18n.lang_display(code)
            it = rumps.MenuItem(label, callback=cb)
            it.state = 1 if code == cur else 0
            menu.add(it)
            items[code] = it
        return menu, items

    @staticmethod
    def _check(items, code):
        for c, it in items.items():
            it.state = 1 if c == code else 0

    def pick_lang(self, sender):           # 界面语言
        code = next((c for c, it in self._ui_lang_items.items() if it is sender), "")
        i18n.set_language(code)
        self._cur_lang = code
        CFG["ui_language"] = code
        set_config_str("ui_language", code)
        self._check(self._ui_lang_items, code)
        self._apply_language()

    def pick_primary(self, sender):        # 主语言=转写语言(下一句即生效)
        code = next((c for c, it in self._primary_items.items() if it is sender), "")
        i18n.set_primary(code)
        self._cur_primary = code
        CFG["primary_language"] = code
        set_config_str("primary_language", code)
        self._check(self._primary_items, code)
        self.primary_menu.title = i18n.t("primary_menu", name=self._disp(code))

    def pick_secondary(self, sender):      # 辅语言=日常夹杂语言
        code = next((c for c, it in self._secondary_items.items() if it is sender), "")
        i18n.set_secondary(code)
        self._cur_secondary = code
        CFG["secondary_language"] = code
        set_config_str("secondary_language", code)
        self._check(self._secondary_items, code)
        self.secondary_menu.title = i18n.t("secondary_menu", name=self._disp_sec(code))

    def _apply_language(self):
        """切界面语言后重刷所有菜单标题(已打开的窗口下次开启时即为新语言)。"""
        self.toggle_item.title = i18n.t("resume") if self.rec.muted else i18n.t("pause")
        self.vault_item.title = self._vault_title()
        self.kw_item.title = i18n.t("keywords")
        self.note_item.title = i18n.t("open_note")
        self.quit_item.title = i18n.t("quit")
        self.tz_menu.title = self._tz_title(self._cur_tz)
        if getattr(self, "_tz_follow", None):
            self._tz_follow.title = i18n.t("follow_system")
        self.ui_lang_menu.title = i18n.t("lang_menu", name=self._disp(self._cur_lang))
        self.primary_menu.title = i18n.t("primary_menu", name=self._disp(self._cur_primary))
        self.secondary_menu.title = i18n.t("secondary_menu", name=self._disp_sec(self._cur_secondary))
        if self._ui_lang_items.get(""):
            self._ui_lang_items[""].title = i18n.t("follow_system")
        if self._primary_items.get(""):
            self._primary_items[""].title = i18n.t("follow_system")
        if self._secondary_items.get(""):
            self._secondary_items[""].title = i18n.t("none")
        self.tick(None)                 # 刷新 count/enroll/spk

    @rumps.timer(2)
    def tick(self, _):
        on_fallback = self.state.get("sink") == "fallback"
        tag = i18n.t("backup") if on_fallback else ""
        dropped = self.state.get("dropped", 0)
        drop = i18n.t("drop", d=dropped) if dropped else ""
        self.count_item.title = i18n.t("count", n=self.state["count"]) + drop + tag
        self.enroll_item.title = self._enroll_title()  # 注册状态/进度实时刷新
        self.spk_item.title = self._spk_title()        # 显示上句相似度，便于校准阈值
        self.model_item.title = self._model_title()   # 常显:任何模式都刷新模型状态(主线程)
        self._refresh_update_item()                    # 更新提示:检查中→✅已最新(绿)/🆕有新版(主线程)
        if self.state.pop("update_apply", False):     # 新版已就位 → 退出本进程,helper 接力替换+重启
            rumps.quit_application()
        ur = self.state.pop("update_result", None)    # 自动更新失败 → 弹窗告知
        if ur:
            rumps.alert(i18n.t("upd_fail_t"), ur)
        if MANAGED_MODEL:                              # 下载结果弹窗只在托管模式有意义
            r = self.state.pop("model_result", None)
            if r == "ok":
                rumps.notification(i18n.t("app_name"), "", i18n.t("model_done"))
            elif r == "fail":
                rumps.alert(i18n.t("model_fail_t"), model_hint(MAC_MODEL_URL, str(MODEL)))
        model_missing = not model_ready(MODEL)         # 任何模式缺模型都亮 ⚠️
        if self.state.get("model_dl"):
            st = "⬇"            # 正在下载模型
        elif model_missing:
            st = "⚠️"           # 模型未下载,点菜单「下载语音模型」
        elif self.state["err"]:
            st = "⚠️"
        elif self.state.get("enrolling"):
            st = "●"            # 正在注册声纹
        elif on_fallback:
            st = "🟠"           # 外置盘掉线，正写内置备用盘
        elif self.rec.muted:
            st = "⏸"
        else:
            st = ""
        # 有图标：正常→空标题(只显 logo)，异常→状态符号；无图标→退回 emoji
        self.title = st if self._has_icon else (st or "🎙")

    def toggle(self, sender):
        self.rec.muted = not self.rec.muted
        sender.title = i18n.t("resume") if self.rec.muted else i18n.t("pause")

    # ---------------- 语音模型：检查 / 从 GitHub 下载（国内可达，绕开 HF） ----------------
    def _model_name(self) -> str:
        """当前所用模型的友好名(目录名/HF repo 名末段)，让用户知道在用哪个模型。"""
        return Path(str(MODEL)).name or str(MODEL)

    def _model_title(self) -> str:
        # 四态常显，让用户一眼确知本地模型状态，绝不黑盒。判定收敛在 model_status_key(可单测)。
        key = model_status_key(bool(self.state.get("model_dl")), model_ready(MODEL), MANAGED_MODEL)
        if key == "model_dling":
            return i18n.t(key, p=self.state.get("model_pct", 0))
        if key == "model_check":
            return i18n.t(key, m=self._model_name())     # 🟢 已就绪：<模型名>
        return i18n.t(key)

    def do_model(self, _):
        if model_ready(MODEL):
            rumps.alert(i18n.t("app_name"), i18n.t("model_check", m=self._model_name()))   # 已就绪：确认状态
            return
        if not MANAGED_MODEL:
            rumps.alert(i18n.t("model_missing_t"), i18n.t("model_missing_b"))  # 直连但路径无模型
            return
        if self.state.get("model_dl"):
            return
        self.state["model_dl"] = True
        self.state["model_pct"] = 0
        threading.Thread(target=self._download_model, daemon=True).start()

    def _download_model(self):
        """后台线程下载,只改 state;结果由主线程的 tick 弹窗(避免跨线程碰 UI)。"""
        ok = download_model(MAC_MODEL_URL, MODEL,
                            lambda f: self.state.__setitem__("model_pct", round(f * 100)))
        self.state["model_dl"] = False
        self.state["model_result"] = "ok" if ok else "fail"

    # ---------------- 更新提示：只查不装，给提示 + 跳下载页 ----------------
    def _check_update(self):
        """后台线程查最新版,只写 state;由主线程 tick 反映到菜单(不跨线程碰 UI)。失败静默。
        VOICELOG_FAKE_LATEST=<版本> 可强制模拟「有新版」用于本地预览/QA,生产不设此变量则无影响。"""
        latest = os.environ.get("VOICELOG_FAKE_LATEST") or update_check.latest_version()
        self.state["update_checked"] = True
        if latest and update_check.is_newer(latest, VERSION):
            self.state["update_latest"] = latest

    def _refresh_update_item(self):
        """更新提示常显(主线程刷新)：下载中=进度；有新版=琥珀黄；已最新=绿；检查中=默认。"""
        app = i18n.t("app_name")
        if self.state.get("updating"):
            self.update_item.title = i18n.t("upd_downloading", p=self.state.get("update_pct", 0))
            return
        latest = self.state.get("update_latest")
        if latest:
            self._style_ad(self.update_item, i18n.t("upd_avail", app=app, v=latest), (0.92, 0.66, 0.15))  # ⚠️ 琥珀黄
        elif self.state.get("update_checked"):
            self._style_ad(self.update_item, i18n.t("upd_latest", app=app, v=VERSION), (0.30, 0.72, 0.40))  # ✅ 绿
        else:
            self.update_item.title = i18n.t("upd_checking")          # 检查更新中…

    def open_releases(self, _=None):
        webbrowser.open(update_check.RELEASES_PAGE)

    # ---------------- 自动更新：确认 → 下载 → 校验 → 覆盖 → 重启 ----------------
    def do_update(self, _):
        latest = self.state.get("update_latest")
        if not latest:                       # 没检测到新版 → 退回打开发布页
            self.open_releases()
            return
        if self.state.get("updating"):
            return
        installed = auto_update.app_bundle_root(sys.executable)
        if not installed:                    # 源码/开发运行,无法自更新 → 打开下载页
            rumps.alert(i18n.t("app_name"), i18n.t("upd_dev"))
            self.open_releases()
            return
        if rumps.alert(i18n.t("upd_confirm_t", v=latest),
                       i18n.t("upd_confirm_b", app=i18n.t("app_name"), v=latest),
                       ok=i18n.t("upd_ok"), cancel=i18n.t("upd_cancel")) != 1:
            return
        self.state["updating"] = True
        self.state["update_pct"] = 0
        threading.Thread(target=self._run_update, args=(latest, installed), daemon=True).start()

    def _run_update(self, latest, installed):
        """后台线程：下载新 dmg → apply_macos(挂载+校验+派 helper)。只改 state,UI 交给 tick。"""
        dmg = Path(tempfile.gettempdir()) / f"VoiceLog-{latest}.dmg"
        ok = auto_update.download_file(
            auto_update.asset_url(latest, "mac"), dmg,
            lambda f: self.state.__setitem__("update_pct", round(f * 100)))
        if not ok:
            self.state["updating"] = False
            self.state["update_result"] = i18n.t("upd_dl_fail")
            return
        applied, msg = auto_update.apply_macos(str(dmg), installed, os.getpid())
        if applied:
            self.state["update_apply"] = True   # tick 退出本进程 → helper 完成替换+重启
        else:
            self.state["updating"] = False
            self.state["update_result"] = msg

    def open_note(self, _):
        note = VAULT / f"{now():%Y-%m-%d}.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        if not note.exists():
            note.write_text("", encoding="utf-8")
        subprocess.run(["open", str(note)])

    def _request_mic(self):
        """启动即用 AVFoundation 显式申请麦克风权限。原因:无权限时 CoreAudio 对本 App 隐藏所有
        输入设备,PortAudio 在查设备阶段(query device -1)就失败、根本走不到能触发系统弹窗的「打开流」。
        显式申请可靠弹窗、可靠让 VoiceLog 出现在「系统设置→隐私→麦克风」。已授权则无操作;被拒由用户去设置开。"""
        try:
            import AVFoundation
            t = AVFoundation.AVMediaTypeAudio
            if AVFoundation.AVCaptureDevice.authorizationStatusForMediaType_(t) == 0:  # 0=未决定
                AVFoundation.AVCaptureDevice.requestAccessForMediaType_completionHandler_(
                    t, lambda granted: None)
        except Exception:
            append_err("request_mic: " + traceback.format_exc().splitlines()[-1])

    def open_homepage(self, _):
        import webbrowser
        webbrowser.open("https://zhaozimin.cn")

    def open_vault_site(self, _):
        import webbrowser
        # 显示名仍写 guangtou.me,但直达飞书资料库(免费引流)
        webbrowser.open("https://my.feishu.cn/wiki/VzguwklrZi272ukWRCccp6kMnre")

    def open_github(self, _):
        import webbrowser
        webbrowser.open("https://github.com/zhaozimin")   # GitHub 主页(分享其他工具)

    def _style_ad(self, item, text, rgb):
        """把广告位做成柔和彩色粗体文字（只染文字色，不加背景）。rgb=(r,g,b) 各 0~1。"""
        try:
            from AppKit import (NSAttributedString, NSColor, NSFont,
                                NSForegroundColorAttributeName, NSFontAttributeName)
            attrs = {
                NSForegroundColorAttributeName:
                    NSColor.colorWithSRGBRed_green_blue_alpha_(rgb[0], rgb[1], rgb[2], 1.0),
                NSFontAttributeName: NSFont.boldSystemFontOfSize_(13),
            }
            item._menuitem.setAttributedTitle_(
                NSAttributedString.alloc().initWithString_attributes_(text, attrs))
        except Exception:
            append_err("style_ad: " + traceback.format_exc().splitlines()[-1])

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # 冻结(PyInstaller)后必须:否则 torch/speechbrain 等用多进程时,
                                       # 子进程(macOS 默认 spawn)会把整个 App 再跑一遍 → 不停弹新 VoiceLog(分叉炸弹)
    VoiceLogApp().run()
