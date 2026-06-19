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
import zlib
import queue
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
import mlx_whisper
from silero_vad import load_silero_vad, VADIterator

from speaker import SpeakerGate
import i18n

# ---------------- 读取配置 ----------------
BASE = Path(__file__).resolve().parent
CFG = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8")) or {}

VERSION = "0.7.0"

SR = 16000
BLOCK = 512  # Silero v5 在 16k 采样率下要求每块正好 512 个采样
MODEL = CFG.get("model", "mlx-community/whisper-large-v3-turbo")
MAX_UTT_SEC = float(CFG.get("max_utterance_sec", 30))
MIN_SILENCE_MS = int(CFG.get("min_silence_ms", 700))
INPUT_DEVICE = CFG.get("input_device", None)  # None=系统默认；可填编号或名字片段(如 "DJI")
VAULT = Path(os.path.expanduser(CFG.get("vault_path", str(BASE.parent / "声音日志"))))
FALLBACK = Path(os.path.expanduser(CFG.get("fallback_path", "~/voicelog-fallback")))
REPLACE = CFG.get("replace") or {}
INITIAL_PROMPT = CFG.get("initial_prompt", "以下是简体中文普通话的日常口语记录。") or None
TERMS = list(CFG.get("terms") or [])  # 识别词库：单写的目标词，注入 prompt 从源头偏置识别(零误伤)
PREROLL = 8  # 句首预留约 0.25s，避免吃掉第一个字

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
UI_LANGUAGE = i18n.set_language(CFG.get("ui_language") or "")  # ""=跟随系统；决定 UI 语言与转写语言


def log_dir() -> Path:
    d = BASE / "logs"
    d.mkdir(exist_ok=True)
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
        cfg = BASE / "config.yaml"
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
        cfg = BASE / "config.yaml"
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
        cfg = BASE / "config.yaml"
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
        cfg = BASE / "config.yaml"
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
    base = INITIAL_PROMPT if (i18n.current() == "zh" and INITIAL_PROMPT) else i18n.prompt()
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
        cfg = BASE / "config.yaml"
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
        self.device = resolve_device(INPUT_DEVICE)
        self.speaker = SpeakerGate(SPEAKER_PROFILE, SPEAKER_THRESHOLD)
        self.speaker_on = SPEAKER_GATE  # 运行时可切换；注册后无需重启即可开启
        self._enroll = None  # 注册采集缓冲：None=未注册中；list=正在旁路收集机主语音
        self._enroll_cancel = False

    def _callback(self, indata, frames, time_info, status):
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
            while True:
                x = self.q.get()
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
        super().__init__("🎙", quit_button=None)
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
        self._cur_lang = CFG.get("ui_language") or ""

        self.count_item = rumps.MenuItem(i18n.t("count", n=0))  # 存引用，标题会变
        self.toggle_item = rumps.MenuItem(i18n.t("pause"), callback=self.toggle)
        self.lang_menu = self._build_lang_menu()            # 「语言」子菜单，随时切换(同时切转写语言)
        self.tz_menu = self._build_tz_menu()                # 「时区」子菜单
        self.vault_item = rumps.MenuItem(self._vault_title(), callback=self.pick_vault)
        self.enroll_item = rumps.MenuItem(self._enroll_title(), callback=self.do_enroll)
        self.spk_item = rumps.MenuItem(self._spk_title(), callback=self.toggle_speaker)
        self.kw_item = rumps.MenuItem(i18n.t("keywords"), callback=self.do_replace)
        self.note_item = rumps.MenuItem(i18n.t("open_note"), callback=self.open_note)
        self.quit_item = rumps.MenuItem(i18n.t("quit"), callback=self.quit_app)
        self.menu = [
            self.count_item,
            self.toggle_item,
            None,  # 分隔线
            self.enroll_item,
            self.spk_item,
            None,  # 分隔线
            self.lang_menu,
            self.tz_menu,
            self.vault_item,
            self.kw_item,
            self.note_item,
            None,  # 分隔线
            rumps.MenuItem(f"VoiceLog v{VERSION}"),  # 版本（无回调=不可点）
            self.quit_item,
        ]

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
        mark = i18n.t("mark_done") if self.state.get("enrolled") else i18n.t("mark_todo")
        return i18n.t("enroll_item", mark=mark)

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
        tail = i18n.t("spk_score", s=s) if (self.rec.speaker_on and s is not None) else ""
        state = i18n.t("on") if self.rec.speaker_on else i18n.t("off")
        return i18n.t("spk_gate", state=state) + tail

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

    # ---------------- 语言（同时切 UI 与转写语言） ----------------
    def _build_lang_menu(self):
        cur = CFG.get("ui_language") or ""
        menu = rumps.MenuItem(i18n.t("lang_menu",
                              name=i18n.lang_display(cur) if cur else i18n.t("follow_system")))
        self._lang_items = {}
        for code in i18n.LANG_ORDER:
            label = i18n.t("follow_system") if code == "" else i18n.lang_display(code)
            item = rumps.MenuItem(label, callback=self.pick_lang)
            item.state = 1 if code == cur else 0
            menu.add(item)
            self._lang_items[code] = item
        return menu

    def pick_lang(self, sender):
        code = next((c for c, it in self._lang_items.items() if it is sender), "")
        i18n.set_language(code)          # 立即生效：之后 t()/转写语言都用新语言
        self._cur_lang = code
        CFG["ui_language"] = code
        set_config_str("ui_language", code)
        for c, it in self._lang_items.items():
            it.state = 1 if c == code else 0
        self._apply_language()

    def _apply_language(self):
        """切语言后重刷所有菜单标题(已打开的窗口下次开启时即为新语言)。"""
        self.toggle_item.title = i18n.t("resume") if self.rec.muted else i18n.t("pause")
        self.vault_item.title = self._vault_title()
        self.kw_item.title = i18n.t("keywords")
        self.note_item.title = i18n.t("open_note")
        self.quit_item.title = i18n.t("quit")
        self.tz_menu.title = self._tz_title(self._cur_tz)
        if getattr(self, "_tz_follow", None):
            self._tz_follow.title = i18n.t("follow_system")
        self.lang_menu.title = i18n.t("lang_menu",
                               name=i18n.lang_display(self._cur_lang) if self._cur_lang else i18n.t("follow_system"))
        if self._lang_items.get(""):
            self._lang_items[""].title = i18n.t("follow_system")
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
        if self.state["err"]:
            self.title = "⚠️"
        elif self.state.get("enrolling"):
            self.title = "●"  # 正在注册声纹
        elif on_fallback:
            self.title = "🟠"  # 外置盘掉线，正写内置备用盘
        elif self.rec.muted:
            self.title = "⏸"
        else:
            self.title = "🎙"

    def toggle(self, sender):
        self.rec.muted = not self.rec.muted
        sender.title = i18n.t("resume") if self.rec.muted else i18n.t("pause")

    def open_note(self, _):
        note = VAULT / f"{now():%Y-%m-%d}.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        if not note.exists():
            note.write_text("", encoding="utf-8")
        subprocess.run(["open", str(note)])

    def quit_app(self, _):
        rumps.quit_application()


if __name__ == "__main__":
    VoiceLogApp().run()
