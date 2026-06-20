#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 Foundation.NSLocale 探测系统语言；无其他业务依赖
[OUTPUT]: 对外提供 t()/set_language()/current()/whisper_lang()/system_lang()/lang_display()/
          enroll_intro()/enroll_script()/prompt()/SUPPORTED/LANG_ORDER
[POS]: voicelog 的多语言中枢。UI 文案 + 注册朗读稿/须知 + whisper 转写语言，全部按当前语言取。
       语言由 config 的 ui_language 决定(""=跟随系统)，切换后 UI 与转写语言同步改变。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

加语言只需在 STRINGS / ENROLL_* / PROMPT / LANG_NAMES 各加一项，并把代码加进 SUPPORTED/LANG_ORDER。
"""

SUPPORTED = ("zh", "en", "ja")
LANG_ORDER = ("", "zh", "en", "ja")   # 菜单顺序，""=跟随系统
LANG_NAMES = {"zh": "简体中文", "en": "English", "ja": "日本語"}

_cur = "zh"        # 界面语言(UI)
_primary = ""      # 主语言=转写语言(""=跟随系统)
_secondary = ""    # 辅语言=日常夹杂语言(""=无)，仅用于强化识别提示


# ---------------- 系统语言探测 ----------------
def system_lang() -> str:
    try:
        from Foundation import NSLocale
        for raw in (NSLocale.preferredLanguages() or []):
            code = str(raw).lower()
            if code.startswith("zh"):
                return "zh"
            if code.startswith("ja"):
                return "ja"
            if code.startswith("en"):
                return "en"
            if code[:2] in SUPPORTED:
                return code[:2]
    except Exception:
        pass
    return "en"


def resolve(code: str) -> str:
    """把配置值解析成受支持语言码：受支持→原样；""或不支持→跟随系统。"""
    return code if code in SUPPORTED else system_lang()


def set_language(code: str) -> str:
    """设界面语言(UI)。"""
    global _cur
    _cur = resolve(code)
    return _cur


def set_primary(code: str) -> None:
    """设主语言(=转写语言)，存原值(""=跟随系统)。"""
    global _primary
    _primary = code if code in SUPPORTED else ""


def set_secondary(code: str) -> None:
    """设辅语言(日常夹杂语言)，存原值(""=无)。"""
    global _secondary
    _secondary = code if code in SUPPORTED else ""


def current() -> str:
    return _cur


def primary() -> str:
    """解析后的主语言(转写语言)：受支持→原样；""→跟随系统。"""
    return resolve(_primary)


def secondary() -> str:
    """辅语言原值(""=无)。"""
    return _secondary


def whisper_lang() -> str:
    """转写语言 = 主语言(与界面语言无关；zh/en/ja 均为合法 whisper 语言码)。"""
    return resolve(_primary)


def lang_display(code: str) -> str:
    return LANG_NAMES.get(code, code)


def t(key: str, **kw) -> str:
    s = STRINGS.get(_cur, STRINGS["en"]).get(key) or STRINGS["en"].get(key) or key
    return s.format(**kw) if kw else s


def enroll_intro() -> str:
    return ENROLL_INTRO.get(_cur, ENROLL_INTRO["en"])


def enroll_script() -> str:
    return ENROLL_SCRIPT.get(_cur, ENROLL_SCRIPT["en"])


def prompt() -> str:
    """whisper 基础提示：主语言的提示 + (有辅语言则)夹杂提示。"""
    p = resolve(_primary)
    base = PROMPT.get(p, PROMPT["en"])
    if _secondary in SUPPORTED and _secondary != p:
        base += PROMPT_MIX.get(p, "").format(sec=LANG_NAMES.get(_secondary, _secondary))
    return base


# ============================================================================
#  UI 短文案
# ============================================================================
STRINGS = {
    "zh": {
        "app_name": "言壤",
        "count": "今日已记：{n} 条", "drop": "，滤除 {d}", "backup": "（备用盘）",
        "pause": "暂停录音", "resume": "继续录音",
        "mark_done": "已注册", "mark_todo": "未注册",
        "enroll_item": "注册我的声音（{mark}）", "enroll_running": "● 正在注册…请持续说话",
        "spk_gate": "声纹门：{state}", "on": "开", "off": "关", "spk_score": "｜上句相似度 {s}",
        "tz": "时区：{tz}", "follow_system": "跟随系统", "none": "无",
        "lang_menu": "界面语言：{name}", "primary_menu": "主语言：{name}", "secondary_menu": "辅语言：{name}",
        "vault": "保存位置 …/{p}（点此更改）",
        "keywords": "关键词管理…", "open_note": "打开今天的笔记", "quit": "退出",
        "model_get": "⬇ 下载语音模型（必需）", "model_check": "🟢 本地模型已就绪",
        "model_dling": "⏳ 正在下载模型 {p}%…", "model_done": "语音模型已就绪，现在可以开始用了。",
        "model_fail_t": "模型下载失败",
        "model_missing": "⚠️ 未找到语音模型（点此查看）",
        "model_missing_t": "未找到语音模型",
        "model_missing_b": "配置(config.yaml)里 model 指向的目录没有模型权重。请检查该路径，或把 model 改为 \"auto\" 让程序自动下载。",
        "upd_checking": "检查更新中…", "upd_latest": "✓ 已是最新版",
        "upd_avail": "🆕 有新版本 v{v} — 点此更新",
        "start": "开始", "cancel": "取消", "save": "保存", "close": "关闭",
        "enroll_win_title": "声纹注册", "kw_win_title": "关键词管理",
        "prepare": "准备中…请开始朗读",
        "progress": "已采集有效语音 {v} / {t} 秒（{p}%）· 用时 {e}s · 请继续朗读",
        "done": "✓ 采集完成 · 提取质量 {q}", "quality_low": "（偏低，建议安静环境重采）",
        "cancelled": "已取消", "failed": "采集失败，请重试",
        "spk_unavail_t": "声纹功能不可用",
        "spk_unavail_b": "未检测到 speechbrain/torch，请在 venv 里安装 speechbrain。",
        "replace_busy_t": "请先结束声纹注册",
        "replace_busy_b": "注册窗口开着时不能同时编辑关键词，请先完成或取消注册。",
        "kw_saved_t": "关键词已保存", "kw_saved_b": "已保存：{r} 条精确纠错 + {t} 个识别词，立即生效。",
        "need_enroll_t": "请先注册声音", "need_enroll_b": "声纹门要先「注册我的声音」才有比对基准。",
        "enroll_fail_t": "打不开注册窗口", "enroll_fail_b": "请查看 logs/err.log。",
        "kw_fail_t": "打不开关键词窗口", "kw_fail_b": "请查看 logs/err.log。",
        "kw_h_title": "关键词管理", "kw_h_sub": "每行一条，「保存」后立即生效。",
        "kw_h_r1a": "写「错词 = 正词」", "kw_h_r1b": "    精确纠错：转写出现错词，就替换成正词",
        "kw_h_r2a": "只写「目标词」", "kw_h_r2b": "       识别词库：让 Whisper 更可能直接听对它",
        "kw_h_eg": "例：克劳德 = Claude      或只写      Obsidian",
        "prompt_terms": " 可能出现的词：{terms}。",
    },
    "en": {
        "app_name": "VoiceLog",
        "count": "Logged today: {n}", "drop": " · filtered {d}", "backup": " (backup)",
        "pause": "Pause recording", "resume": "Resume recording",
        "mark_done": "registered", "mark_todo": "not set",
        "enroll_item": "Register my voice ({mark})", "enroll_running": "● Registering… keep speaking",
        "spk_gate": "Voiceprint gate: {state}", "on": "On", "off": "Off", "spk_score": " · last match {s}",
        "tz": "Timezone: {tz}", "follow_system": "Follow system", "none": "None",
        "lang_menu": "Interface: {name}", "primary_menu": "Primary language: {name}", "secondary_menu": "Secondary language: {name}",
        "vault": "Save to …/{p} (click to change)",
        "keywords": "Keywords…", "open_note": "Open today's note", "quit": "Quit",
        "model_get": "⬇ Download speech model (required)", "model_check": "🟢 Local model ready",
        "model_dling": "⏳ Downloading model {p}%…", "model_done": "Speech model ready. You're all set.",
        "model_fail_t": "Model download failed",
        "model_missing": "⚠️ Speech model not found (click for help)",
        "model_missing_t": "Speech model not found",
        "model_missing_b": "The 'model' path in config.yaml has no model weights. Check the path, or set model to \"auto\" to auto-download.",
        "upd_checking": "Checking for updates…", "upd_latest": "✓ Up to date",
        "upd_avail": "🆕 Update available v{v} — click to get it",
        "start": "Start", "cancel": "Cancel", "save": "Save", "close": "Close",
        "enroll_win_title": "Voiceprint setup", "kw_win_title": "Keyword manager",
        "prepare": "Getting ready… start reading",
        "progress": "Captured {v} / {t}s of speech ({p}%) · {e}s elapsed · keep reading",
        "done": "✓ Done · quality {q}", "quality_low": " (low — try again somewhere quiet)",
        "cancelled": "Cancelled", "failed": "Failed, please try again",
        "spk_unavail_t": "Voiceprint unavailable",
        "spk_unavail_b": "speechbrain/torch not found. Install speechbrain in the venv.",
        "replace_busy_t": "Finish voiceprint setup first",
        "replace_busy_b": "Can't edit keywords while the setup window is open. Finish or cancel it first.",
        "kw_saved_t": "Keywords saved", "kw_saved_b": "Saved: {r} corrections + {t} vocab terms. Active now.",
        "need_enroll_t": "Register your voice first",
        "need_enroll_b": "The gate needs an enrolled voiceprint to compare against.",
        "enroll_fail_t": "Can't open setup window", "enroll_fail_b": "See logs/err.log.",
        "kw_fail_t": "Can't open keyword window", "kw_fail_b": "See logs/err.log.",
        "kw_h_title": "Keyword manager", "kw_h_sub": "One per line. Changes apply on save.",
        "kw_h_r1a": "Type  wrong = right", "kw_h_r1b": "    Exact fix: replace the wrong word in transcripts",
        "kw_h_r2a": "Type just a word", "kw_h_r2b": "       Vocabulary: helps Whisper hear it correctly",
        "kw_h_eg": "e.g.   teh = the       or just       Obsidian",
        "prompt_terms": " Possible terms: {terms}.",
    },
    "ja": {
        "app_name": "VoiceLog",
        "count": "本日の記録：{n} 件", "drop": "・除外 {d}", "backup": "（予備）",
        "pause": "録音を一時停止", "resume": "録音を再開",
        "mark_done": "登録済み", "mark_todo": "未登録",
        "enroll_item": "声紋を登録（{mark}）", "enroll_running": "● 登録中…話し続けてください",
        "spk_gate": "声紋ゲート：{state}", "on": "オン", "off": "オフ", "spk_score": "・類似度 {s}",
        "tz": "タイムゾーン：{tz}", "follow_system": "システムに従う", "none": "なし",
        "lang_menu": "表示言語：{name}", "primary_menu": "主言語：{name}", "secondary_menu": "副言語：{name}",
        "vault": "保存先 …/{p}（クリックで変更）",
        "keywords": "キーワード管理…", "open_note": "今日のノートを開く", "quit": "終了",
        "model_get": "⬇ 音声モデルをダウンロード（必須）", "model_check": "🟢 ローカルモデル準備完了",
        "model_dling": "⏳ モデルDL {p}%…", "model_done": "音声モデルの準備完了。使い始められます。",
        "model_fail_t": "モデルのダウンロード失敗",
        "model_missing": "⚠️ 音声モデルが見つかりません（クリック）",
        "model_missing_t": "音声モデルが見つかりません",
        "model_missing_b": "config.yaml の model が指すフォルダにモデルがありません。パスを確認するか、model を \"auto\" にして自動DLしてください。",
        "upd_checking": "アップデートを確認中…", "upd_latest": "✓ 最新版です",
        "upd_avail": "🆕 新バージョン v{v} — クリックで更新",
        "start": "開始", "cancel": "キャンセル", "save": "保存", "close": "閉じる",
        "enroll_win_title": "声紋登録", "kw_win_title": "キーワード管理",
        "prepare": "準備中…読み始めてください",
        "progress": "音声 {v} / {t} 秒（{p}%）・経過 {e}s ・読み続けてください",
        "done": "✓ 完了 · 品質 {q}", "quality_low": "（低め・静かな場所で再登録を）",
        "cancelled": "キャンセルしました", "failed": "失敗しました。もう一度お試しください",
        "spk_unavail_t": "声紋機能が使えません",
        "spk_unavail_b": "speechbrain/torch が見つかりません。venv に speechbrain を入れてください。",
        "replace_busy_t": "先に声紋登録を終えてください",
        "replace_busy_b": "登録ウィンドウを開いている間はキーワードを編集できません。先に完了かキャンセルを。",
        "kw_saved_t": "キーワードを保存しました", "kw_saved_b": "保存：修正 {r} 件＋認識語 {t} 件。すぐに有効です。",
        "need_enroll_t": "先に声紋を登録してください",
        "need_enroll_b": "声紋ゲートには登録済みの声紋が必要です。",
        "enroll_fail_t": "登録ウィンドウを開けません", "enroll_fail_b": "logs/err.log を確認してください。",
        "kw_fail_t": "キーワードウィンドウを開けません", "kw_fail_b": "logs/err.log を確認してください。",
        "kw_h_title": "キーワード管理", "kw_h_sub": "1行に1つ。保存するとすぐ反映されます。",
        "kw_h_r1a": "「誤 = 正」と入力", "kw_h_r1b": "    正確な置換：書き起こしの誤りを正しい語に",
        "kw_h_r2a": "単語だけ入力", "kw_h_r2b": "       認識語彙：Whisper が正しく聞き取りやすく",
        "kw_h_eg": "例：　くらうど = Claude　または　Obsidian",
        "prompt_terms": " 出てくる語：{terms}。",
    },
}

# ============================================================================
#  注册「须知页」文案（第一屏简短引导）
# ============================================================================
ENROLL_INTRO = {
    "zh": """接下来，请照着屏幕上的几句话，用平常聊天的语气念出来。

这几句话讲的正是这款应用怎么工作、怎么保护你的隐私——
念一遍，你就同时做完了两件事：完成声纹注册，也搞懂了它怎么用。

准备好就点「开始」；采够音色会自动停，大约二十秒。

你的声音日记，只属于你。""",
    "en": """Next, please read the lines on the screen aloud, in your normal speaking voice.

What they say is exactly how this app works and how it protects your privacy —
read them once and you do two things at once: finish your voiceprint, and learn how to use it.

When you're ready, click Start. It stops on its own once it has enough of your voice, in about twenty seconds.

Your voice diary — yours alone.""",
    "ja": """これから、画面に表示される文章を、いつもの話し方で声に出して読んでください。

その内容は、このアプリの仕組みとプライバシーの守り方そのものです。
一度読めば、声紋の登録と使い方の理解が同時にできます。

準備ができたら「開始」を押してください。声が十分に集まると、約二十秒で自動的に止まります。

あなたの声の日記は、あなただけのもの。""",
}

# ============================================================================
#  注册朗读稿（用户亲口念出「应用怎么工作」，读即学 + 同时采声纹）
# ============================================================================
ENROLL_SCRIPT = {
    "zh": """你好，我正在录入我自己的声音。
这款应用全程在我这台电脑上运行，不联网、也不上传，更不会读取我的任何其他数据。
它录到的声音，转成文字以后就会立刻丢弃，绝不写进硬盘；记下来的文字，也只保存在我自己的电脑里。
平时它就安静地待在菜单栏里，在后台帮我把说过的话记成当天的笔记。我只要像平常一样开口说话就行，不用动手做任何操作。
这些笔记会按日期自动分好，我随时可以打开今天的看一看；要是有一阵子不想被记录，也可以在菜单栏里点一下暂停。
等它记住我的音色以后，就只会把我本人说的话记进日志，自动忽略外放的视频、电视，还有旁边人说话的声音。
而我不出声的时候，它也会保持安静，不会自己乱编出内容来。
所以我可以放心地用它，安安静静地记录我每天的想法和灵感。""",
    "en": """Hi, I'm recording my own voice right now.
This app runs entirely on my own computer. It never goes online, never uploads anything, and never reads any of my other data.
The sound it records is turned into text and then discarded right away — it is never written to disk, and the text it keeps stays only on my own computer.
Most of the time it just sits quietly in the menu bar, turning what I say into today's note in the background. I only have to talk as usual; I don't have to do anything.
The notes are filed by date automatically, and I can open today's note anytime. If I don't want to be recorded for a while, I can pause it from the menu bar.
Once it has learned my voice, it only logs what I myself say, and automatically ignores videos, the television, and other people talking nearby.
And when I'm not speaking, it stays quiet and never makes anything up.
So I can use it with peace of mind to record my thoughts and ideas every day.""",
    "ja": """こんにちは。今、自分の声を登録しています。
このアプリは、すべて自分のパソコンの中だけで動きます。ネットにはつながらず、アップロードもせず、ほかのデータを読み取ることもありません。
録音した音声は、文字にしたらすぐに捨てられ、ディスクに保存されることは決してありません。書き起こした文字も、自分のパソコンの中だけに残ります。
普段はメニューバーの中で静かに待っていて、話した言葉をその日のノートに記録してくれます。いつものように話すだけでよく、特別な操作はいりません。
ノートは日付ごとに自動で整理され、いつでも今日のぶんを開けます。しばらく記録されたくないときは、メニューバーから一時停止できます。
私の声を覚えたあとは、自分が話した言葉だけを記録し、外で流れている動画やテレビ、まわりの人の声は自動で無視します。
そして私が話していないときは静かにしていて、勝手に内容を作り出すことはありません。
だから安心して、毎日の考えやひらめきを記録できます。""",
}

# ============================================================================
#  whisper initial_prompt 基础提示（按语言；用户的 TERMS 词库会再追加）
# ============================================================================
PROMPT = {
    "zh": "以下是简体中文普通话的日常口语记录。",
    "en": "The following is a casual everyday spoken log in English.",
    "ja": "以下は日本語の日常的な話し言葉の記録です。",
}

# 辅语言夹杂提示(按主语言措辞，{sec}=辅语言名)
PROMPT_MIX = {
    "zh": "其中可能夹杂{sec}。",
    "en": " It may contain some {sec}.",
    "ja": "{sec}が混じることがあります。",
}
