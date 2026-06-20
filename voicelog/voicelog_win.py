#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VoiceLog · 跨平台托盘版 (Windows 主用,亦可在 macOS/Linux 跑)

[INPUT]: 依赖 sounddevice(采集)、silero_vad(切句)、transcribe_fw.FasterWhisper(转写)、
         pystray(托盘)、PIL(图标)、speaker.SpeakerGate(声纹)、i18n；读 config.yaml
[OUTPUT]: 可执行入口 main();与 voicelog_menubar.py(macOS/mlx) 对等的 Windows 实现
[POS]: voicelog 的 Windows 端入口。复用跨平台内核(speaker/i18n/VAD/三道门/幻觉过滤),
       仅把 mlx_whisper→faster_whisper、rumps→pystray、PyObjC 窗口→托盘菜单+系统通知。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

流程(与 macOS 端同构)：麦克风 → sounddevice 实时采集 → Silero VAD 按句切
      → ① 时长门 → ② 能量/近场门 → ③ 声纹门 → faster-whisper 转写
      → 复读/幻觉过滤 + 术语纠错 → 按时区写入当天 Markdown。音频转写即弃,绝不写盘。
Beta 说明:无弹窗 UI——设置/关键词改 config.yaml(托盘「打开配置文件」),声纹注册走托盘+系统通知。
"""
import os
import re
import sys
import zlib
import queue
import time
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
from PIL import Image, ImageDraw
import pystray
from silero_vad import load_silero_vad, VADIterator

from speaker import SpeakerGate
from transcribe_fw import FasterWhisper, DEFAULT_MODEL
from model_fetch import model_ready, download_model, WIN_MODEL_URL
import i18n

os.environ.setdefault("HF_HUB_DISABLE_XET", "1")  # 关掉会卡死的 hf_xet(ECAPA 若走 HF)

VERSION = "0.9.0"

# ---------------- 路径：只读资源(RES) 与 可写用户数据(DATA) 解耦 ----------------
# Windows: 数据落 %APPDATA%\VoiceLog;其他平台(便于在 Mac 上验证)落 ~/.voicelog-win。
FROZEN = getattr(sys, "frozen", False)
RES = Path(getattr(sys, "_MEIPASS", "")) if FROZEN else Path(__file__).resolve().parent
if os.name == "nt":
    DATA = Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "VoiceLog"
else:
    DATA = Path.home() / ".voicelog-win"
DATA.mkdir(parents=True, exist_ok=True)

CONFIG_PATH = DATA / "config.yaml"
if not CONFIG_PATH.exists():                      # 首次运行:播种内置默认配置到用户区
    seed = RES / "config.example.yaml"
    if seed.exists():
        CONFIG_PATH.write_text(seed.read_text(encoding="utf-8"), encoding="utf-8")

CFG = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) if CONFIG_PATH.exists() else {}
CFG = CFG or {}

# ---------------- 配置项 ----------------
SR = 16000
BLOCK = 512                                       # Silero v5 @16k 要求每块正好 512 样本
# Windows 用 faster-whisper 模型(与 mac 的 mlx `model` 区分);留空用内置默认。
# 模型来源:model_win 写 "auto"/留空(打包默认)→ 托管,放 DATA/models,缺失则从 GitHub 下载(国内可达);
# 写 HF repo 名或本地路径 → 直接用(开发/进阶)。
_mw = (CFG.get("model_win") or "").strip()
MANAGED_WIN = _mw.lower() in ("", "auto")
MODEL_LOCAL = DATA / "models" / "whisper-ct2-turbo"      # 普通版:下载到这里
MODEL_BUNDLED = RES / "models" / "whisper-ct2-turbo"     # 离线版:模型已打进包
if MANAGED_WIN:
    MODEL_WIN = str(MODEL_BUNDLED) if model_ready(MODEL_BUNDLED) else str(MODEL_LOCAL)
else:
    MODEL_WIN = _mw
MODEL_DIR = os.path.expanduser(CFG.get("model_win_dir") or "~/voicelog-models/faster-whisper")
MAX_UTT_SEC = float(CFG.get("max_utterance_sec", 30))
MIN_SILENCE_MS = int(CFG.get("min_silence_ms", 700))
INPUT_DEVICE = CFG.get("input_device", None)
VAULT = Path(os.path.expanduser(CFG.get("vault_path") or "~/VoiceLog/声音日志"))
FALLBACK = Path(os.path.expanduser(CFG.get("fallback_path") or "~/voicelog-fallback"))
REPLACE = CFG.get("replace") or {}
INITIAL_PROMPT = CFG.get("initial_prompt", "以下是简体中文普通话的日常口语记录。") or None
TERMS = list(CFG.get("terms") or [])
PREROLL = 8
NO_AUDIO_TIMEOUT_SEC = float(CFG.get("no_audio_timeout_sec", 5))

VAD_THRESHOLD = float(CFG.get("vad_threshold", 0.6))
MIN_SPEECH_MS = int(CFG.get("min_speech_ms", 300))
ENERGY_GATE = bool(CFG.get("energy_gate", True))
MIN_RMS_DBFS = float(CFG.get("min_rms_dbfs", -45.0))
SPEAKER_GATE = bool(CFG.get("speaker_gate", False))
SPEAKER_THRESHOLD = float(CFG.get("speaker_threshold", 0.35))
SPEAKER_PROFILE = CFG.get("speaker_profile", "~/voicelog-models/speaker_profile.npy")
ENROLL_VOICED_SEC = float(CFG.get("enroll_voiced_sec", 20))
ENROLL_MAX_SEC = float(CFG.get("enroll_max_sec", 120))
ENROLL_VOICE_FLOOR = float(CFG.get("enroll_voice_floor_dbfs", -40.0))

i18n.set_language(CFG.get("ui_language") or "")
i18n.set_primary(CFG.get("primary_language") or "")
i18n.set_secondary(CFG.get("secondary_language") or "")

try:
    _TZ = ZoneInfo(CFG["timezone"]) if CFG.get("timezone") else None
except Exception:
    _TZ = None


def now() -> datetime.datetime:
    return datetime.datetime.now(_TZ)


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


# ============================================================================
#  幻觉过滤 / 能量 / 纠错 —— 与 macOS 端同一套「大脑」(逻辑须保持一致)
# ============================================================================
_HALLUCINATIONS = {
    "优优独播剧场YoYo Television Series Exclusive",
    "请不吝点赞 订阅 转发 打赏支持明镜与点点栏目", "明镜与点点栏目",
    "字幕由Amara.org社区提供", "本字幕由观众提供", "请订阅我的频道",
    "谢谢观看", "谢谢大家", "下集再见",
}


def _norm(s: str) -> str:
    return "".join(ch.lower() for ch in s if ch.isalnum())


_DROP_EXACT = {_norm(s) for s in _HALLUCINATIONS | set(CFG.get("drop_phrases") or [])}
_DROP_SUB = {d for d in _DROP_EXACT if len(d) >= 8}


def _looped(text: str) -> bool:
    """复读循环检测:8+ 连续同字 / 字符多样性崩塌 / 长文 zlib 压缩比 >3.0。"""
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
    rms = float(np.sqrt(np.mean(np.square(x)))) if x.size else 0.0
    return 20.0 * np.log10(rms + 1e-9)


def apply_replace(text: str) -> str:
    """专名纠错。ASCII 词按词边界,避免 Cloud→Claude 误伤 iCloud。"""
    for k, v in REPLACE.items():
        if k.isascii() and k.strip():
            text = re.sub(rf"(?<![A-Za-z]){re.escape(k)}(?![A-Za-z])", v, text)
        else:
            text = text.replace(k, v)
    return text


def current_prompt():
    base = INITIAL_PROMPT if (i18n.primary() == "zh" and INITIAL_PROMPT) else i18n.prompt()
    if TERMS:
        base = (base + i18n.t("prompt_terms", terms="、".join(TERMS))).strip()
    return base or None


def set_config_flag(key: str, value: bool) -> None:
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8")
        new = re.sub(rf"(?m)^{re.escape(key)}:.*$", f"{key}: {'true' if value else 'false'}", text)
        if new != text:
            CONFIG_PATH.write_text(new, encoding="utf-8")
    except Exception:
        append_err(f"写回 {key} 失败")


# ---------------- 写入(掉盘回退,绝不丢字) ----------------
def write_line(text: str) -> str:
    ts = now()
    line = f"- **{ts:%H:%M}** {text}\n"
    for base, tag in ((VAULT, "vault"), (FALLBACK, "fallback")):
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


def resolve_device(dev):
    if dev is None or dev == "":
        return None
    try:
        return int(dev)
    except (ValueError, TypeError):
        pass
    try:
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0 and str(dev).lower() in d["name"].lower():
                return i
    except Exception:
        pass
    return None


# ============================================================================
#  录音 + 转写线程(含掉线自愈看门狗,与 macOS v0.8.1 同构)
# ============================================================================
class Recorder(threading.Thread):
    def __init__(self, state: dict, transcriber: FasterWhisper):
        super().__init__(daemon=True)
        self.state = state
        self.tx = transcriber
        self.q: queue.Queue = queue.Queue()
        self.muted = False
        self.vad = load_silero_vad()
        self.speaker = SpeakerGate(SPEAKER_PROFILE, SPEAKER_THRESHOLD)
        self.speaker_on = SPEAKER_GATE
        self._enroll = None
        self._enroll_cancel = False
        self._last_audio = time.monotonic()

    def _callback(self, indata, frames, time_info, status):
        self._last_audio = time.monotonic()       # 心跳:回调还在烧=麦还活着
        if status:
            self.state["status"] = str(status)
        mono = indata[:, 0].copy()
        buf = self._enroll
        if buf is not None:
            buf.append(mono)
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
                sd.sleep(3000)

    def _stream_loop(self):
        device = resolve_device(INPUT_DEVICE)     # 每次重开都重解析:拔插后编号会变
        vad_iter = VADIterator(self.vad, threshold=VAD_THRESHOLD, sampling_rate=SR,
                               min_silence_duration_ms=MIN_SILENCE_MS, speech_pad_ms=100)
        preroll = deque(maxlen=PREROLL)
        buf, triggered = [], False
        self.state["err"] = ""
        self._last_audio = time.monotonic()
        with sd.InputStream(samplerate=SR, channels=1, dtype="float32",
                            blocksize=BLOCK, device=device, callback=self._callback):
            self.state["live"] = True
            while True:
                try:
                    x = self.q.get(timeout=1)
                except queue.Empty:
                    # 队列空:用心跳辨真假死。回调停摆超时=设备掉线,主动重开流。
                    if time.monotonic() - self._last_audio > NO_AUDIO_TIMEOUT_SEC and not self.muted:
                        raise RuntimeError("audio device stalled (no callbacks)")
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
                        vad_iter.reset_states()
                    if utt is not None and self._accept(utt):
                        self._transcribe(utt)

    def _accept(self, utt: np.ndarray) -> bool:
        if utt.size < MIN_SPEECH_MS * SR // 1000:
            return self._drop("short")
        if ENERGY_GATE and _rms_dbfs(utt) < MIN_RMS_DBFS:
            return self._drop("far")
        if self.speaker_on:
            ok, score = self.speaker.verify(utt)
            self.state["last_score"] = round(score, 3)
            if not ok:
                return self._drop("speaker")
        return True

    def _drop(self, reason: str) -> bool:
        self.state["dropped"] = self.state.get("dropped", 0) + 1
        return False

    def _transcribe(self, utt: np.ndarray):
        if MANAGED_WIN and not model_ready(MODEL_WIN):
            return                                # 模型未下载,别硬转;托盘菜单提示用户去下
        try:
            text = self.tx.transcribe(utt, language=i18n.whisper_lang(),
                                      initial_prompt=current_prompt())
        except Exception:
            append_err("transcribe: " + traceback.format_exc().splitlines()[-1])
            return
        if not text or is_junk(text):
            return
        text = apply_replace(text)
        sink = write_line(text)
        if sink == "lost":
            return
        self.state["count"] += 1
        self.state["last"] = text
        self.state["sink"] = sink

    # ---------------- 声纹注册(质量驱动,托盘触发,系统通知反馈) ----------------
    def enroll(self, on_done):
        self._enroll_cancel = False

        def _run():
            self._enroll = []
            voiced_frames, voiced_sec, elapsed, idx = [], 0.0, 0.0, 0
            while (not self._enroll_cancel and voiced_sec < ENROLL_VOICED_SEC
                   and elapsed < ENROLL_MAX_SEC):
                sd.sleep(200)
                elapsed += 0.2
                frames = self._enroll or []
                for f in frames[idx:]:
                    if _rms_dbfs(f) > ENROLL_VOICE_FLOOR:
                        voiced_frames.append(f)
                        voiced_sec += len(f) / SR
                idx = len(frames)
                self.state["enroll_voiced"] = round(voiced_sec, 1)
            self._enroll = None
            wav = np.concatenate(voiced_frames) if voiced_frames else np.zeros(0, np.float32)
            ok = bool(wav.size) and self.speaker.enroll(wav)
            self.state["enrolled"] = self.speaker.enrolled
            on_done(ok, self.speaker.last_quality)

        threading.Thread(target=_run, daemon=True).start()


# ============================================================================
#  托盘图标(pystray) —— 深色圆角底 + 白 logo,任意任务栏底色都可见
# ============================================================================
def _tray_image() -> Image.Image:
    """生成 64x64 托盘图:深色圆角方 + 居中白 logo(在亮/暗任务栏都清晰)。"""
    N, ss = 64, 4
    big = N * ss
    img = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, big - 1, big - 1], radius=int(big * 0.22), fill=255)
    bg = Image.new("RGBA", (big, big), (0x1a, 0x1a, 0x1c, 255))
    img.paste(bg, (0, 0), mask)
    try:
        logo = Image.open(RES / "assets" / "icon.png").convert("RGBA")
        lw = int(big * 0.72)
        lh = round(lw * logo.height / logo.width)
        logo = logo.resize((lw, lh), Image.LANCZOS)
        img.alpha_composite(logo, ((big - lw) // 2, (big - lh) // 2))
    except Exception:
        pass
    return img.resize((N, N), Image.LANCZOS)


class TrayApp:
    def __init__(self):
        self.state = {"count": 0, "last": "", "err": "", "live": False, "status": "",
                      "sink": "vault", "dropped": 0, "enrolling": False,
                      "enrolled": False, "last_score": None}
        self.tx = FasterWhisper(MODEL_WIN, download_root=MODEL_DIR)
        self.rec = Recorder(self.state, self.tx)
        self.state["enrolled"] = self.rec.speaker.enrolled
        self.icon = pystray.Icon("VoiceLog", _tray_image(), "VoiceLog", menu=self._menu())

    # ---------------- 菜单(标题/勾选用 callable,update_menu 时重算) ----------------
    def _menu(self):
        I = pystray.MenuItem
        return pystray.Menu(
            I(lambda _: i18n.t("count", n=self.state["count"])
              + (i18n.t("drop", d=self.state["dropped"]) if self.state["dropped"] else ""),
              None, enabled=False),
            I(lambda _: i18n.t("resume") if self.rec.muted else i18n.t("pause"), self._toggle),
            I(lambda _: self._model_title(), self._download_model_click,
              enabled=lambda _: not self.state.get("model_dl")),
            pystray.Menu.SEPARATOR,
            I(lambda _: (i18n.t("enroll_running") if self.state["enrolling"]
                         else i18n.t("enroll_item",
                                     mark=(i18n.t("mark_done") if self.state["enrolled"]
                                           else i18n.t("mark_todo")))),
              self._enroll, enabled=lambda _: not self.state["enrolling"]),
            I(lambda _: self._spk_title(), self._toggle_speaker),
            pystray.Menu.SEPARATOR,
            I(i18n.t("open_note"), self._open_note),
            I("打开配置文件 / Open config", self._open_config),
            pystray.Menu.SEPARATOR,
            I(f"VoiceLog v{VERSION} (Windows Beta)", None, enabled=False),
            I("📣 作者主页：zhaozimin.cn", self._open_homepage),
            I(i18n.t("quit"), self._quit),
        )

    def _spk_title(self):
        s = self.state.get("last_score")
        tail = i18n.t("spk_score", s=s) if (self.rec.speaker_on and s is not None) else ""
        return i18n.t("spk_gate", state=i18n.t("on") if self.rec.speaker_on else i18n.t("off")) + tail

    # ---------------- 语音模型：检查 / 从 GitHub 下载（国内可达，绕开 HF） ----------------
    def _model_title(self):
        if not MANAGED_WIN or model_ready(MODEL_WIN):
            return i18n.t("model_check")
        if self.state.get("model_dl"):
            return i18n.t("model_dling", p=self.state.get("model_pct", 0))
        return i18n.t("model_get")

    def _download_model_click(self, icon, item):
        if model_ready(MODEL_WIN):
            icon.notify(i18n.t("model_check"), "VoiceLog")
            return
        if self.state.get("model_dl"):
            return
        self.state["model_dl"] = True
        self.state["model_pct"] = 0
        icon.update_menu()
        icon.notify(i18n.t("model_dling", p=0), "VoiceLog")

        def run():
            ok = download_model(WIN_MODEL_URL, MODEL_LOCAL,
                                lambda f: self.state.__setitem__("model_pct", round(f * 100)))
            self.state["model_dl"] = False
            icon.notify(i18n.t("model_done") if ok else i18n.t("model_fail_t"), "VoiceLog")
            icon.update_menu()

        threading.Thread(target=run, daemon=True).start()

    # ---------------- 回调 ----------------
    def _toggle(self, icon, item):
        self.rec.muted = not self.rec.muted
        icon.update_menu()

    def _toggle_speaker(self, icon, item):
        if not self.rec.speaker.enrolled and not self.rec.speaker_on:
            icon.notify(i18n.t("need_enroll_b"), i18n.t("need_enroll_t"))
            return
        self.rec.speaker_on = not self.rec.speaker_on
        set_config_flag("speaker_gate", self.rec.speaker_on)
        icon.update_menu()

    def _enroll(self, icon, item):
        if self.state["enrolling"]:
            return
        if not self.rec.speaker.available():
            icon.notify(i18n.t("spk_unavail_b"), i18n.t("spk_unavail_t"))
            return
        self.state["enrolling"] = True
        icon.update_menu()
        icon.notify(i18n.t("enroll_running") + " · " + i18n.t("enroll_item", mark="").strip(),
                    "VoiceLog")

        def done(ok, quality):
            self.state["enrolling"] = False
            q = quality if isinstance(quality, (int, float)) else None
            msg = (i18n.t("done", q=f"{round(q*100)}%" if q is not None else "—") if ok
                   else i18n.t("failed"))
            icon.notify(msg, "VoiceLog")
            icon.update_menu()

        self.rec.enroll(done)

    def _open_note(self, icon, item):
        note = VAULT / f"{now():%Y-%m-%d}.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        if not note.exists():
            note.write_text("", encoding="utf-8")
        _open_path(note)

    def _open_config(self, icon, item):
        _open_path(CONFIG_PATH)

    def _open_homepage(self, icon, item):
        import webbrowser
        webbrowser.open("https://zhaozimin.cn")

    def _quit(self, icon, item):
        icon.stop()

    # ---------------- 后台刷新菜单/标题 ----------------
    def _refresh_loop(self):
        while True:
            time.sleep(2)
            try:
                if MANAGED_WIN and not model_ready(MODEL_WIN):
                    tag = (f" · ⬇{self.state.get('model_pct', 0)}%" if self.state.get("model_dl")
                           else " · ⚠ 需下载模型")
                elif self.state["err"]:
                    tag = " · ⚠"
                elif self.rec.muted:
                    tag = " · ⏸"
                else:
                    tag = ""
                self.icon.title = f"VoiceLog · {i18n.t('count', n=self.state['count']).strip()}{tag}"
                self.icon.update_menu()
            except Exception:
                pass

    def run(self):
        self.rec.start()
        threading.Thread(target=self._refresh_loop, daemon=True).start()
        self.icon.run()


def _open_path(p: Path):
    try:
        if os.name == "nt":
            os.startfile(str(p))                  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)])
        else:
            subprocess.run(["xdg-open", str(p)])
    except Exception:
        append_err("open_path: " + traceback.format_exc().splitlines()[-1])


def main():
    TrayApp().run()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()   # 冻结后必须:防多进程子进程把整个 App 重跑(分叉炸弹)
    main()
