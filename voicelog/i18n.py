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
        "open_config": "打开配置文件（高级，改后重启生效）",
        "settings_menu": "参数设置…", "settings_title": "参数设置",
        "settings_sub": "拖滑块或直接改数字；保存即时生效（切句/断句两项会自动重连麦克风）。",
        "settings_reset": "恢复默认", "settings_saved_t": "设置已保存", "settings_saved_b": "新参数已即时生效。",
        "model_get": "⬇ 下载语音模型（必需）", "model_check": "🟢 本地模型已就绪：{m}",
        "model_dling": "⏳ 正在下载模型 {p}%…", "model_done": "语音模型已就绪，现在可以开始用了。",
        "model_fail_t": "模型下载失败",
        "model_missing": "⚠️ 未找到语音模型（点此查看）",
        "model_missing_t": "未找到语音模型",
        "model_missing_b": "配置(config.yaml)里 model 指向的目录没有模型权重。请检查该路径，或把 model 改为 \"auto\" 让程序自动下载。",
        "cur_version": "当前版本：{app} v{v}",
        "upd_checking": "检查更新中…", "upd_latest": "✅ 已是最新版本：{app} v{v}",
        "upd_avail": "⚠️ 点击更新到最新版本：{app} v{v}",
        "upd_downloading": "⏳ 正在下载更新 {p}%…",
        "upd_confirm_t": "发现新版本 v{v}", "upd_ok": "立即更新", "upd_cancel": "稍后",
        "upd_confirm_b": "现在自动下载并更新到 {app} v{v}？\n更新后会自动重启，你的数据和模型不受影响。",
        "upd_dl_fail": "下载失败，请稍后重试，或点菜单去下载页手动更新。",
        "upd_fail_t": "更新失败",
        "upd_dev": "当前为源码/开发运行，无法自动更新；已为你打开下载页。",
        "open_logs": "打开日志文件夹",
        "welcome_t": "欢迎使用 言壤",
        "welcome_b": "言壤 会在后台聆听你的麦克风，把你说的话实时记成当天的文字笔记。\n\n• 音频从不存盘，文字只留在你自己的电脑\n\n开始三步：\n1. 点菜单「⬇ 下载语音模型」(首次必需)\n2. 可选「注册我的声音」：只记你本人，自动忽略外放/旁人\n3. 正常说话即可，图标常驻菜单栏\n\n笔记保存在：\n{v}\n（可在菜单「保存位置」更改）",
        "mic_denied_t": "麦克风未授权",
        "mic_denied_b": "言壤 需要麦克风才能记录。请在「系统设置 → 隐私与安全性 → 麦克风」里打开 言壤(VoiceLog)，然后重开本应用。",
        "mic_open_settings": "打开设置",
        "write_lost_b": "写入失败：磁盘可能已满或不可写，请检查「保存位置」。",
        "fell_back_b": "外置盘已掉线，正在写入内置备用盘（自动、临时，数据安全）。",
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
        "enroll_fail_t": "打不开注册窗口", "enroll_fail_b": "出了点问题。点「打开日志」找到 err.log，发给作者可帮忙排查。",
        "kw_fail_t": "打不开关键词窗口", "kw_fail_b": "出了点问题。点「打开日志」找到 err.log，发给作者可帮忙排查。",
        "kw_h_title": "关键词管理", "kw_h_sub": "每行一条，「保存」后立即生效。",
        "kw_h_r1a": "写「错词 = 正词」", "kw_h_r1b": "    精确纠错：转写出现错词，就替换成正词",
        "kw_h_r2a": "只写「目标词」", "kw_h_r2b": "       识别词库：让 Whisper 更可能直接听对它",
        "kw_h_eg": "例：克劳德 = Claude      或只写      Obsidian",
        "prompt_terms": " 可能出现的词：{terms}。",
        # ---- 全窗口产品(V1)：侧边栏 + 四页 ----
        "win_open": "打开主窗口",
        "nav_home": "首页", "nav_history": "历史记录", "nav_settings": "设置", "nav_about": "关于",
        "home_listening": "正在聆听", "home_paused": "已暂停",
        "home_sub_on": "在后台把你说的话记成今天的笔记。", "home_sub_off": "已暂停记录，点下方按钮继续。",
        "home_stats": "今日 {n} 条 · 滤除 {d} 条", "home_saveto": "保存于 {p}",
        "home_feed_title": "今天的记录",
        "home_feed_empty": "今天还没有记录。正常说话，文字会实时出现在这里。",
        "hist_search_ph": "搜索全部历史…", "hist_empty": "还没有历史记录。",
        "hist_pick": "← 在左侧选择某一天查看", "hist_found": "在 {d} 天里找到 {n} 行",
        "set_params_title": "门控参数", "set_more_title": "其他",
        "set_path_label": "保存位置", "set_change_btn": "更改…",
        "set_enroll_btn": "注册我的声音…", "set_kw_btn": "关键词管理…", "set_advanced_btn": "高级配置…",
        "set_save_btn": "保存设置",
        "about_tagline": "本地实时语音日志",
        "about_intro": "言壤 在你自己的电脑上实时聆听麦克风，把你说的话记成当天的文字笔记。\n\n• 全程本地运行，不联网、不上传\n• 音频转写后立即丢弃，绝不写盘\n• 注册声纹后只记你本人，自动忽略外放视频与旁人\n\n笔记按日期自动归档，随时可在「历史记录」里翻看。",
        "about_check_btn": "检查更新", "about_home_btn": "作者主页", "about_obsidian_btn": "资料库",
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
        "open_config": "Open config (advanced; restart to apply)",
        "settings_menu": "Settings…", "settings_title": "Settings",
        "settings_sub": "Drag sliders or type a number; saved changes apply immediately (VAD/silence auto-reconnect the mic).",
        "settings_reset": "Reset", "settings_saved_t": "Settings saved", "settings_saved_b": "New settings applied.",
        "model_get": "⬇ Download speech model (required)", "model_check": "🟢 Local model ready: {m}",
        "model_dling": "⏳ Downloading model {p}%…", "model_done": "Speech model ready. You're all set.",
        "model_fail_t": "Model download failed",
        "model_missing": "⚠️ Speech model not found (click for help)",
        "model_missing_t": "Speech model not found",
        "model_missing_b": "The 'model' path in config.yaml has no model weights. Check the path, or set model to \"auto\" to auto-download.",
        "cur_version": "Current: {app} v{v}",
        "upd_checking": "Checking for updates…", "upd_latest": "✅ Latest: {app} v{v}",
        "upd_avail": "⚠️ Click to update to {app} v{v}",
        "upd_downloading": "⏳ Downloading update {p}%…",
        "upd_confirm_t": "New version v{v}", "upd_ok": "Update now", "upd_cancel": "Later",
        "upd_confirm_b": "Download and update to {app} v{v} now?\nThe app restarts automatically; your data and model are untouched.",
        "upd_dl_fail": "Download failed. Try again later, or use the menu to open the download page.",
        "upd_fail_t": "Update failed",
        "upd_dev": "Running from source/dev — auto-update unavailable; opened the download page instead.",
        "open_logs": "Open logs folder",
        "welcome_t": "Welcome to VoiceLog",
        "welcome_b": "VoiceLog listens to your microphone in the background and turns what you say into today's text notes.\n\n• Audio is never saved to disk; text stays only on your computer\n\nThree steps:\n1. Click ⬇ Download speech model (required the first time)\n2. Optional: Register my voice — log only you, ignore others/playback\n3. Just talk; the icon stays in the menu bar\n\nNotes saved to:\n{v}\n(change via Save location)",
        "mic_denied_t": "Microphone not allowed",
        "mic_denied_b": "VoiceLog needs the microphone. Enable VoiceLog under System Settings → Privacy & Security → Microphone, then reopen the app.",
        "mic_open_settings": "Open Settings",
        "write_lost_b": "Write failed: the disk may be full or read-only. Check Save location.",
        "fell_back_b": "External disk went offline; writing to the built-in backup (automatic, temporary, data safe).",
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
        "enroll_fail_t": "Can't open setup window", "enroll_fail_b": "Something went wrong. Click Open logs to find err.log and send it to the developer.",
        "kw_fail_t": "Can't open keyword window", "kw_fail_b": "Something went wrong. Click Open logs to find err.log and send it to the developer.",
        "kw_h_title": "Keyword manager", "kw_h_sub": "One per line. Changes apply on save.",
        "kw_h_r1a": "Type  wrong = right", "kw_h_r1b": "    Exact fix: replace the wrong word in transcripts",
        "kw_h_r2a": "Type just a word", "kw_h_r2b": "       Vocabulary: helps Whisper hear it correctly",
        "kw_h_eg": "e.g.   teh = the       or just       Obsidian",
        "prompt_terms": " Possible terms: {terms}.",
        # ---- Full-window product (V1): sidebar + four pages ----
        "win_open": "Open main window",
        "nav_home": "Home", "nav_history": "History", "nav_settings": "Settings", "nav_about": "About",
        "home_listening": "Listening", "home_paused": "Paused",
        "home_sub_on": "Turning what you say into today's note, in the background.",
        "home_sub_off": "Recording paused. Click the button below to resume.",
        "home_stats": "{n} today · {d} filtered", "home_saveto": "Saved to {p}",
        "home_feed_title": "Today's log",
        "home_feed_empty": "Nothing logged yet today. Just talk — text appears here live.",
        "hist_search_ph": "Search all history…", "hist_empty": "No history yet.",
        "hist_pick": "← Pick a day on the left", "hist_found": "{n} lines across {d} days",
        "set_params_title": "Gate parameters", "set_more_title": "More",
        "set_path_label": "Save location", "set_change_btn": "Change…",
        "set_enroll_btn": "Register my voice…", "set_kw_btn": "Keywords…", "set_advanced_btn": "Advanced config…",
        "set_save_btn": "Save settings",
        "about_tagline": "Local real-time voice log",
        "about_intro": "VoiceLog listens to your microphone on your own computer and turns what you say into today's text notes.\n\n• Runs fully on-device — never online, never uploaded\n• Audio is discarded right after transcription, never written to disk\n• Once your voiceprint is set, it logs only you and ignores playback and other people\n\nNotes are filed by date automatically; browse them anytime under History.",
        "about_check_btn": "Check for updates", "about_home_btn": "Author", "about_obsidian_btn": "Library",
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
        "open_config": "設定ファイルを開く（上級。再起動で反映）",
        "settings_menu": "設定…", "settings_title": "設定",
        "settings_sub": "スライダーか数値で調整。保存で即反映（VAD/無音は自動でマイク再接続）。",
        "settings_reset": "デフォルトに戻す", "settings_saved_t": "設定を保存しました", "settings_saved_b": "新しい設定を適用しました。",
        "model_get": "⬇ 音声モデルをダウンロード（必須）", "model_check": "🟢 ローカルモデル準備完了：{m}",
        "model_dling": "⏳ モデルDL {p}%…", "model_done": "音声モデルの準備完了。使い始められます。",
        "model_fail_t": "モデルのダウンロード失敗",
        "model_missing": "⚠️ 音声モデルが見つかりません（クリック）",
        "model_missing_t": "音声モデルが見つかりません",
        "model_missing_b": "config.yaml の model が指すフォルダにモデルがありません。パスを確認するか、model を \"auto\" にして自動DLしてください。",
        "cur_version": "現在のバージョン：{app} v{v}",
        "upd_checking": "アップデートを確認中…", "upd_latest": "✅ 最新版です：{app} v{v}",
        "upd_avail": "⚠️ クリックで {app} v{v} に更新",
        "upd_downloading": "⏳ 更新をDL中 {p}%…",
        "upd_confirm_t": "新バージョン v{v}", "upd_ok": "今すぐ更新", "upd_cancel": "後で",
        "upd_confirm_b": "{app} v{v} に今すぐ更新しますか？\n更新後に自動で再起動します。データとモデルは保持されます。",
        "upd_dl_fail": "ダウンロード失敗。後で再試行するか、メニューからダウンロードページを開いてください。",
        "upd_fail_t": "更新に失敗",
        "upd_dev": "ソース/開発実行のため自動更新は不可。ダウンロードページを開きました。",
        "open_logs": "ログフォルダを開く",
        "welcome_t": "言壤へようこそ",
        "welcome_b": "言壤 はバックグラウンドでマイクを聞き、話した内容をその日のテキストノートに記録します。\n\n• 音声は保存されず、テキストはあなたのPC内だけに残ります\n\n3ステップ：\n1.「⬇ 音声モデルをダウンロード」(初回必須)\n2. 任意「声紋を登録」：自分だけ記録、外部音/他人は無視\n3. 普通に話すだけ。アイコンはメニューバーに常駐\n\nノート保存先：\n{v}\n(「保存先」で変更可)",
        "mic_denied_t": "マイクが許可されていません",
        "mic_denied_b": "言壤 にはマイクが必要です。システム設定 → プライバシーとセキュリティ → マイク で 言壤(VoiceLog) をオンにし、アプリを再起動してください。",
        "mic_open_settings": "設定を開く",
        "write_lost_b": "書き込み失敗：ディスクが満杯か書き込み不可の可能性。「保存先」を確認してください。",
        "fell_back_b": "外部ディスクがオフラインです。内蔵バックアップに書き込み中（自動・一時的・データは安全）。",
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
        "enroll_fail_t": "登録ウィンドウを開けません", "enroll_fail_b": "問題が発生しました。「ログを開く」で err.log を見つけ、開発者に送ってください。",
        "kw_fail_t": "キーワードウィンドウを開けません", "kw_fail_b": "問題が発生しました。「ログを開く」で err.log を見つけ、開発者に送ってください。",
        "kw_h_title": "キーワード管理", "kw_h_sub": "1行に1つ。保存するとすぐ反映されます。",
        "kw_h_r1a": "「誤 = 正」と入力", "kw_h_r1b": "    正確な置換：書き起こしの誤りを正しい語に",
        "kw_h_r2a": "単語だけ入力", "kw_h_r2b": "       認識語彙：Whisper が正しく聞き取りやすく",
        "kw_h_eg": "例：　くらうど = Claude　または　Obsidian",
        "prompt_terms": " 出てくる語：{terms}。",
        # ---- フルウィンドウ版(V1)：サイドバー + 4ページ ----
        "win_open": "メインウィンドウを開く",
        "nav_home": "ホーム", "nav_history": "履歴", "nav_settings": "設定", "nav_about": "情報",
        "home_listening": "聞き取り中", "home_paused": "一時停止中",
        "home_sub_on": "話した内容をバックグラウンドで今日のノートに記録しています。",
        "home_sub_off": "記録を一時停止中です。下のボタンで再開できます。",
        "home_stats": "本日 {n} 件 · 除外 {d} 件", "home_saveto": "保存先 {p}",
        "home_feed_title": "今日の記録",
        "home_feed_empty": "今日の記録はまだありません。普通に話せば、ここにリアルタイムで表示されます。",
        "hist_search_ph": "全履歴を検索…", "hist_empty": "履歴がまだありません。",
        "hist_pick": "← 左から日付を選択", "hist_found": "{d} 日間で {n} 行を発見",
        "set_params_title": "ゲートのパラメータ", "set_more_title": "その他",
        "set_path_label": "保存先", "set_change_btn": "変更…",
        "set_enroll_btn": "声紋を登録…", "set_kw_btn": "キーワード管理…", "set_advanced_btn": "詳細設定…",
        "set_save_btn": "設定を保存",
        "about_tagline": "ローカル・リアルタイム音声ログ",
        "about_intro": "言壤 は自分のパソコン上でマイクを聞き取り、話した内容をその日のテキストノートに記録します。\n\n• すべて端末内で動作。ネット接続もアップロードもなし\n• 音声は文字化後すぐに破棄され、ディスクには保存されません\n• 声紋を登録すれば自分の声だけを記録し、外部の音や他人の声は無視します\n\nノートは日付ごとに自動整理。「履歴」からいつでも閲覧できます。",
        "about_check_btn": "アップデートを確認", "about_home_btn": "作者ページ", "about_obsidian_btn": "ライブラリ",
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
