#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 AppKit(PyObjC) 的 NSWindow/NSVisualEffectView/NSScrollView/NSTextView/NSSearchField/NSBox 等；
         依赖 ui_common 的 KeyWindow/BtnTarget/make_rich_label/字体颜色/floor_regular；
         依赖 settings_ui 的 make_param_card/read_card_values/PARAMS/CARD_H/CARD_GAP/_Tgt；
         运行时通过 sys.modules[type(app).__module__] 取主程序的活引擎(VAULT/now/set_config_values/apply_settings...)
[OUTPUT]: 对外提供 MainWindow(app)——「正儿八经版」(V1) 的 Dock 主窗口：侧边栏 + 四页(首页/历史/设置/关于)；
          导入即给 rumps 的 NSApplication delegate 补「点 Dock 图标重开窗」钩子(objc.Category)
[POS]: voicelog 的「全窗口产品外壳」。与菜单栏(lite 外壳)共用同一个 VoiceLogApp、同一 Recorder、同一 2s 心跳——
       本文件只画界面、转调 app 的现成回调与引擎函数，绝不复制业务逻辑。设置页的参数卡复用 settings_ui 卡片工厂。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

形态切换在主程序：VOICELOG_FLAVOR=full / config.app_flavor=full → 创建本窗口 + floor_regular(常驻 Dock)；
否则维持菜单栏 lite 形态，本文件不被导入，零影响。所有 AppKit 操作均在主线程(rumps 回调/Timer)。
"""
import re
import sys

import objc
from Foundation import NSObject, NSMakeRect, NSMakeSize, NSInsetRect
from AppKit import (
    NSView, NSTextField, NSButton, NSScrollView, NSTextView, NSSearchField,
    NSVisualEffectView, NSBox, NSColor, NSFont, NSApp, NSBezierPath,
    NSBezelBorder, NSNoBorder, NSViewWidthSizable,
    NSWindowStyleMaskTitled, NSWindowStyleMaskClosable, NSWindowStyleMaskMiniaturizable,
    NSBackingStoreBuffered, NSBoxSeparator,
    NSVisualEffectMaterialSidebar, NSVisualEffectBlendingModeBehindWindow,
    NSVisualEffectStateActive, NSTextAlignmentRight,
)

from ui_common import (
    KeyWindow, BtnTarget, make_rich_label,
    title_font, body_font, C_PRIMARY, C_SECONDARY, C_TERTIARY,
)
from settings_ui import make_param_card, read_card_values, PARAMS, CARD_H, CARD_GAP, _Tgt
import i18n

# ---------------- 尺寸常量（固定窗口：所见即所设，免去自适应布局的脆弱） ----------------
WIN_W, WIN_H = 940, 640
SIDEBAR_W = 200
CONTENT_W = WIN_W - SIDEBAR_W
NAV_H = 36
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(frame, s, font, color, align=None):
    """只读、无边框、透明背景的文字标签——本模块的层次化文案基元。"""
    t = NSTextField.alloc().initWithFrame_(frame)
    t.setStringValue_(s); t.setBezeled_(False); t.setEditable_(False); t.setSelectable_(False)
    t.setDrawsBackground_(False); t.setFont_(font); t.setTextColor_(color)
    if align is not None:
        t.setAlignment_(align)
    return t


def _btn(frame, title, cb, retain, key_equiv=None):
    """圆角按钮 + 回调桥；BtnTarget 必须被 python 侧持有(塞进 retain)否则点击失效。"""
    b = NSButton.alloc().initWithFrame_(frame)
    b.setTitle_(title); b.setBezelStyle_(1)
    if key_equiv:
        b.setKeyEquivalent_(key_equiv)
    t = BtnTarget.alloc().initWithCallback_(cb)
    b.setTarget_(t); b.setAction_("invoke:")
    retain.append(t)
    return b


def _scroll_textview(frame, font_size=13.0, editable=False):
    """带竖向滚动条的只读文本区(今日实时流 / 历史内容 / 搜索结果共用)。返回 (scroll, textview)。"""
    scroll = NSScrollView.alloc().initWithFrame_(frame)
    scroll.setHasVerticalScroller_(True)
    scroll.setHasHorizontalScroller_(False)
    scroll.setBorderType_(NSBezelBorder)
    scroll.setDrawsBackground_(False)
    w = frame.size.width
    tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, w, frame.size.height))
    tv.setEditable_(editable); tv.setSelectable_(True)
    tv.setFont_(NSFont.systemFontOfSize_(font_size))
    tv.setTextContainerInset_(NSMakeSize(12, 12))
    tv.setMinSize_(NSMakeSize(0, 0)); tv.setMaxSize_(NSMakeSize(1.0e7, 1.0e7))
    tv.setVerticallyResizable_(True); tv.setHorizontallyResizable_(False)
    tv.setAutoresizingMask_(NSViewWidthSizable)
    tv.textContainer().setWidthTracksTextView_(True)
    scroll.setDocumentView_(tv)
    return scroll, tv


def _separator(x, y, w):
    b = NSBox.alloc().initWithFrame_(NSMakeRect(x, y, w, 1))
    b.setBoxType_(NSBoxSeparator)
    return b


# ============================================================================
#  侧边栏导航项：自绘选中高亮(圆角填充) + 点击切页。一个 NSView，最少的活动部件。
# ============================================================================
class _NavItem(NSView):
    @objc.python_method
    def configure(self, key, title, cb, width):
        self._key = key
        self._cb = cb
        self._sel = False
        self._lbl = _text(NSMakeRect(16, 7, width - 24, 22), title,
                          NSFont.systemFontOfSize_(13.5), C_PRIMARY())
        self.addSubview_(self._lbl)

    @objc.python_method
    def set_selected(self, on):
        self._sel = on
        self._lbl.setFont_(NSFont.boldSystemFontOfSize_(13.5) if on
                           else NSFont.systemFontOfSize_(13.5))
        self.setNeedsDisplay_(True)

    def drawRect_(self, dirty):
        if getattr(self, "_sel", False):
            r = NSInsetRect(self.bounds(), 6, 2)
            p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(r, 7.0, 7.0)
            NSColor.controlAccentColor().colorWithAlphaComponent_(0.15).setFill()
            p.fill()

    def mouseDown_(self, ev):
        if getattr(self, "_cb", None):
            self._cb(self._key)


# ============================================================================
#  窗口代理：关闭按钮 = 隐藏窗口(orderOut)，App 仍驻 Dock；点 Dock 图标再重开。
# ============================================================================
class _WinDelegate(NSObject):
    def initWithCb_(self, cb):
        self = objc.super(_WinDelegate, self).init()
        self._cb = cb
        return self

    def windowShouldClose_(self, sender):
        try:
            self._cb()
        except Exception:
            pass
        return False        # 不真关——只隐藏，保活整个 App


# ============================================================================
#  给 rumps 的 NSApplication delegate 补「点 Dock 图标重开窗」(objc.Category·同名类)。
#  self._app 是 VoiceLogApp 实例的 __dict__，从中取 main_win 即可——无需任何全局变量。
# ============================================================================
def _install_reopen():
    from rumps import rumps as _rm

    class NSApp(objc.Category(_rm.NSApp)):                    # noqa: F811 同名才是合法 Category
        def applicationShouldHandleReopen_hasVisibleWindows_(self, sender, has_visible):
            try:
                mw = self._app.get("main_win")
                if mw is not None:
                    mw.show()
            except Exception:
                pass
            return True


try:
    _install_reopen()
except Exception:
    pass    # 钩子失败不致命：菜单栏「打开主窗口」永远是可靠退路


# ============================================================================
#  可翻转容器：原点在左上，让滚动内容自上而下排列(设置页卡片堆 / 历史日期列)。
# ============================================================================
class _Flipped(NSView):
    def isFlipped(self):
        return True


# ============================================================================
#  主窗口（纯 Python 编排类）：侧边栏 + 四页。复用 app 的回调与引擎，自身只管画与刷。
# ============================================================================
class MainWindow:
    def __init__(self, app):
        self.app = app
        self.core = sys.modules[type(app).__module__]   # 主程序模块(活引擎)：VAULT/now/set_config_values...
        self._retain = []          # 持有 ObjC target/delegate，防 GC
        self._nav = {}             # key -> _NavItem
        self._pages = {}           # key -> NSView
        self._cur = None
        self._feed_mtime = -1      # 今日流文件 mtime 缓存：没变就不重读、不打断滚动
        self._hist_cur = None      # 历史页当前所选日期(清空搜索时恢复)
        self._set_rows = []        # 设置页 [(spec, slider, field), ...]

        win = KeyWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIN_W, WIN_H),
            NSWindowStyleMaskTitled | NSWindowStyleMaskClosable | NSWindowStyleMaskMiniaturizable,
            NSBackingStoreBuffered, False)
        win.setTitle_(i18n.t("app_name"))
        win.center()
        win.setReleasedWhenClosed_(False)
        self._delegate = _WinDelegate.alloc().initWithCb_(self._hide)
        win.setDelegate_(self._delegate)
        self.win = win
        root = win.contentView()

        self._build_sidebar(root)
        cont = NSView.alloc().initWithFrame_(NSMakeRect(SIDEBAR_W, 0, CONTENT_W, WIN_H))
        root.addSubview_(cont)
        self._cont = cont

        self._pages["home"] = self._build_home()
        self._pages["history"] = self._build_history()
        self._pages["settings"] = self._build_settings()
        self._pages["about"] = self._build_about()
        for p in self._pages.values():
            p.setHidden_(True)
            cont.addSubview_(p)
        self.select("home")

    # ---------------- 侧边栏 ----------------
    @objc.python_method
    def _build_sidebar(self, root):
        side = NSVisualEffectView.alloc().initWithFrame_(NSMakeRect(0, 0, SIDEBAR_W, WIN_H))
        try:
            side.setMaterial_(NSVisualEffectMaterialSidebar)
            side.setBlendingMode_(NSVisualEffectBlendingModeBehindWindow)
            side.setState_(NSVisualEffectStateActive)
        except Exception:
            pass
        root.addSubview_(side)
        side.addSubview_(make_rich_label(
            NSMakeRect(18, WIN_H - 78, SIDEBAR_W - 26, 56),
            [(i18n.t("app_name") + "\n", title_font(20), C_PRIMARY()),
             (i18n.t("about_tagline"), body_font(10.5), C_SECONDARY())]))
        nav = [("home", "🏠  " + i18n.t("nav_home")),
               ("history", "🕘  " + i18n.t("nav_history")),
               ("settings", "⚙️  " + i18n.t("nav_settings")),
               ("about", "ℹ️  " + i18n.t("nav_about"))]
        y = WIN_H - 134
        for key, label in nav:
            it = _NavItem.alloc().initWithFrame_(NSMakeRect(8, y, SIDEBAR_W - 16, NAV_H))
            it.configure(key, label, self.select, SIDEBAR_W - 16)
            side.addSubview_(it)
            self._nav[key] = it
            y -= NAV_H + 6

    # ---------------- 页面切换 ----------------
    @objc.python_method
    def select(self, key):
        for k, it in self._nav.items():
            it.set_selected(k == key)
        for k, p in self._pages.items():
            p.setHidden_(k != key)
        self._cur = key
        if key == "home":
            self._refresh_home()
        elif key == "history":
            self._reload_history()

    @objc.python_method
    def show(self):
        try:
            self.win.makeKeyAndOrderFront_(None)
            NSApp.activateIgnoringOtherApps_(True)
        except Exception:
            pass

    @objc.python_method
    def _hide(self):
        try:
            self.win.orderOut_(None)
        except Exception:
            pass

    @objc.python_method
    def refresh(self):
        """app 的 2s 心跳调用：只刷正在看的首页(其余页静态，切到时再加载)。"""
        try:
            if self._cur == "home" and not self.win.isMiniaturized():
                self._refresh_home()
        except Exception:
            pass

    # ======================================================================
    #  首页 / 录入：状态 + 大开关 + 统计 + 今日实时流
    # ======================================================================
    @objc.python_method
    def _build_home(self):
        cw, ch = CONTENT_W, WIN_H
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        PAD = 28
        self._home_status = _text(NSMakeRect(PAD, ch - 66, cw - 2 * PAD - 160, 32),
                                  "", title_font(22), C_PRIMARY())
        self._home_sub = _text(NSMakeRect(PAD, ch - 90, cw - 2 * PAD - 160, 18),
                               "", body_font(12.5), C_SECONDARY())
        self._home_toggle = _btn(NSMakeRect(cw - PAD - 150, ch - 80, 150, 34),
                                 "", self._toggle, self._retain)
        v.addSubview_(self._home_status)
        v.addSubview_(self._home_sub)
        v.addSubview_(self._home_toggle)
        v.addSubview_(_separator(PAD, ch - 108, cw - 2 * PAD))

        self._home_model = _text(NSMakeRect(PAD, ch - 134, cw - 2 * PAD, 18), "", body_font(12.5), C_PRIMARY())
        self._home_spk = _text(NSMakeRect(PAD, ch - 156, cw - 2 * PAD, 18), "", body_font(12.5), C_PRIMARY())
        self._home_stats = _text(NSMakeRect(PAD, ch - 178, cw - 2 * PAD, 18), "", body_font(12.5), C_SECONDARY())
        self._home_save = _text(NSMakeRect(PAD, ch - 200, cw - 2 * PAD, 18), "", body_font(11.5), C_TERTIARY())
        for w in (self._home_model, self._home_spk, self._home_stats, self._home_save):
            v.addSubview_(w)

        v.addSubview_(_text(NSMakeRect(PAD, ch - 234, cw - 2 * PAD, 20),
                            i18n.t("home_feed_title"), title_font(13), C_PRIMARY()))
        scroll, tv = _scroll_textview(NSMakeRect(PAD, PAD, cw - 2 * PAD, ch - 234 - PAD))
        self._feed_tv = tv
        v.addSubview_(scroll)
        return v

    @objc.python_method
    def _toggle(self):
        rec = self.app.rec
        rec.muted = not rec.muted
        try:    # 与菜单栏的「暂停/继续」标题保持一致
            self.app.toggle_item.title = i18n.t("resume") if rec.muted else i18n.t("pause")
        except Exception:
            pass
        self._refresh_home()

    @objc.python_method
    def _refresh_home(self):
        app, core = self.app, self.core
        rec, st = app.rec, app.state
        muted = rec.muted
        live = bool(st.get("live"))
        dot = "⏸" if muted else ("🟢" if live else "🟡")
        self._home_status.setStringValue_(
            f"{dot} " + (i18n.t("home_paused") if muted else i18n.t("home_listening")))
        self._home_sub.setStringValue_(i18n.t("home_sub_off") if muted else i18n.t("home_sub_on"))
        self._home_toggle.setTitle_(i18n.t("resume") if muted else i18n.t("pause"))
        try:
            self._home_model.setStringValue_(app._model_title())
            self._home_spk.setStringValue_(app._spk_title())
        except Exception:
            pass
        self._home_stats.setStringValue_(
            i18n.t("home_stats", n=st.get("count", 0), d=st.get("dropped", 0)))
        self._home_save.setStringValue_(i18n.t("home_saveto", p=str(core.VAULT)))
        self._refresh_feed()

    @objc.python_method
    def _refresh_feed(self):
        core = self.core
        note = core.VAULT / f"{core.now():%Y-%m-%d}.md"
        try:
            m = note.stat().st_mtime if note.exists() else 0
        except Exception:
            m = 0
        if m == self._feed_mtime:
            return
        self._feed_mtime = m
        try:
            txt = note.read_text(encoding="utf-8") if note.exists() else ""
        except Exception:
            txt = ""
        self._feed_tv.setString_(txt or i18n.t("home_feed_empty"))
        try:    # 跟到最新一行
            self._feed_tv.scrollRangeToVisible_((self._feed_tv.string().length(), 0))
        except Exception:
            pass

    # ======================================================================
    #  历史记录：左侧日期列 + 右侧内容；顶部跨全部日志的搜索
    # ======================================================================
    @objc.python_method
    def _build_history(self):
        cw, ch = CONTENT_W, WIN_H
        PAD = 24
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        sf = NSSearchField.alloc().initWithFrame_(NSMakeRect(PAD, ch - 52, cw - 2 * PAD, 28))
        try:
            sf.setPlaceholderString_(i18n.t("hist_search_ph"))
        except Exception:
            pass
        st = _Tgt.alloc().initWithCb_(self._do_search)
        sf.setTarget_(st); sf.setAction_("act:")
        self._retain.append(st)
        self._search = sf
        v.addSubview_(sf)

        list_w, gap = 190, 14
        top = ch - 52 - 12
        list_scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(PAD, PAD, list_w, top - PAD))
        list_scroll.setHasVerticalScroller_(True)
        list_scroll.setBorderType_(NSBezelBorder)
        list_scroll.setDrawsBackground_(False)
        self._date_doc = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, list_w, top - PAD))
        list_scroll.setDocumentView_(self._date_doc)
        self._date_scroll = list_scroll
        v.addSubview_(list_scroll)

        cx = PAD + list_w + gap
        scroll, tv = _scroll_textview(NSMakeRect(cx, PAD, cw - cx - PAD, top - PAD))
        self._hist_tv = tv
        v.addSubview_(scroll)
        return v

    @objc.python_method
    def _dates(self):
        try:
            return sorted((p.stem for p in self.core.VAULT.glob("*.md") if _DATE_RE.match(p.stem)),
                          reverse=True)
        except Exception:
            return []

    @objc.python_method
    def _reload_history(self):
        for sub in list(self._date_doc.subviews()):
            sub.removeFromSuperview()
        dates = self._dates()
        row_h = 30
        doc_h = max(len(dates) * row_h, self._date_scroll.frame().size.height)
        self._date_doc.setFrameSize_(NSMakeSize(self._date_scroll.frame().size.width, doc_h))
        list_w = self._date_doc.frame().size.width
        tgt = _Tgt.alloc().initWithCb_(lambda s: self._show_day(str(s.title())))
        self._retain.append(tgt)
        for i, d in enumerate(dates):
            b = NSButton.alloc().initWithFrame_(NSMakeRect(4, i * row_h, list_w - 8, row_h - 4))
            b.setTitle_(d); b.setBordered_(False); b.setBezelStyle_(1)
            b.setAlignment_(4)   # NSTextAlignmentLeft
            b.setTarget_(tgt); b.setAction_("act:")
            self._date_doc.addSubview_(b)
        if dates:
            self._show_day(dates[0])
        else:
            self._hist_cur = None
            self._hist_tv.setString_(i18n.t("hist_empty"))

    @objc.python_method
    def _show_day(self, date):
        self._hist_cur = date
        note = self.core.VAULT / f"{date}.md"
        try:
            txt = note.read_text(encoding="utf-8") if note.exists() else ""
        except Exception:
            txt = ""
        self._hist_tv.setString_(txt or i18n.t("hist_pick"))
        self._hist_tv.scrollRangeToVisible_((0, 0))

    @objc.python_method
    def _do_search(self, sender):
        q = str(sender.stringValue()).strip()
        if not q:
            if self._hist_cur:
                self._show_day(self._hist_cur)
            else:
                self._hist_tv.setString_(i18n.t("hist_pick"))
            return
        out, days, lines = [], 0, 0
        for d in self._dates():
            note = self.core.VAULT / f"{d}.md"
            try:
                matched = [ln for ln in note.read_text(encoding="utf-8").splitlines()
                           if ln.startswith("- ") and q in ln]
            except Exception:
                matched = []
            if matched:
                days += 1
                lines += len(matched)
                out.append("## " + d)
                out.extend(matched)
                out.append("")
        head = i18n.t("hist_found", d=days, n=lines)
        self._hist_tv.setString_(head + "\n\n" + ("\n".join(out) if out else i18n.t("hist_empty")))
        self._hist_tv.scrollRangeToVisible_((0, 0))

    # ======================================================================
    #  设置：滚动卡片(复用 settings_ui 卡片工厂) + 保存位置 + 入口按钮 + 底部保存条
    # ======================================================================
    @objc.python_method
    def _build_settings(self):
        cw, ch = CONTENT_W, WIN_H
        core = self.app and self.core
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        FOOT = 56
        # 底部固定保存条
        self._set_saved = _text(NSMakeRect(28, FOOT // 2 - 8, cw - 200, 18), "", body_font(12), C_SECONDARY())
        v.addSubview_(self._set_saved)
        v.addSubview_(_btn(NSMakeRect(cw - 28 - 132, 12, 132, 32),
                           i18n.t("set_save_btn"), self._save_settings, self._retain, key_equiv="\r"))
        v.addSubview_(_separator(0, FOOT, cw))

        # 滚动区(翻转容器，自上而下)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, FOOT, cw, ch - FOOT))
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setBorderType_(NSNoBorder)
        scroll.setDrawsBackground_(False)
        doc_w = cw - 16
        doc = _Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, doc_w, 10))
        CW = doc_w - 56
        cur = {"vad_threshold": core.VAD_THRESHOLD, "min_speech_ms": core.MIN_SPEECH_MS,
               "min_silence_ms": core.MIN_SILENCE_MS, "min_rms_dbfs": core.MIN_RMS_DBFS,
               "speaker_threshold": core.SPEAKER_THRESHOLD,
               "speaker_min_verify_sec": core.SPEAKER_MIN_VERIFY_SEC,
               "max_utterance_sec": core.MAX_UTT_SEC}

        y = 18
        doc.addSubview_(_text(NSMakeRect(28, y, CW, 20), i18n.t("set_params_title"), title_font(14), C_PRIMARY()))
        y += 30
        for spec in PARAMS:
            card, sld, fld = make_param_card(spec, cur.get(spec[0], spec[5]), CW, self._retain)
            card.setFrameOrigin_((28, y))
            doc.addSubview_(card)
            self._set_rows.append((spec, sld, fld))
            y += CARD_H + CARD_GAP

        y += 8
        doc.addSubview_(_separator(28, y, CW)); y += 16
        doc.addSubview_(_text(NSMakeRect(28, y, CW, 20), i18n.t("set_more_title"), title_font(14), C_PRIMARY()))
        y += 30
        doc.addSubview_(_text(NSMakeRect(28, y + 3, 90, 20), i18n.t("set_path_label"), title_font(12.5), C_PRIMARY()))
        self._set_path_val = _text(NSMakeRect(120, y + 3, CW - 120 - 100, 20),
                                   str(core.VAULT), body_font(12), C_SECONDARY())
        doc.addSubview_(self._set_path_val)
        doc.addSubview_(_btn(NSMakeRect(28 + CW - 90, y, 90, 26),
                             i18n.t("set_change_btn"), self._change_path, self._retain))
        y += 40
        doc.addSubview_(_btn(NSMakeRect(28, y, 168, 30), i18n.t("set_enroll_btn"),
                             lambda: self.app.do_enroll(None), self._retain))
        doc.addSubview_(_btn(NSMakeRect(28 + 178, y, 150, 30), i18n.t("set_kw_btn"),
                             lambda: self.app.do_replace(None), self._retain))
        doc.addSubview_(_btn(NSMakeRect(28 + 178 + 160, y, 150, 30), i18n.t("set_advanced_btn"),
                             lambda: self.app.open_config(None), self._retain))
        y += 46

        doc.setFrameSize_(NSMakeSize(doc_w, max(y, ch - FOOT)))
        scroll.setDocumentView_(doc)
        v.addSubview_(scroll)
        return v

    @objc.python_method
    def _save_settings(self):
        vals = read_card_values(self._set_rows)
        try:
            self.core.set_config_values(vals)
            self.core.apply_settings(self.app, vals)
            self._set_saved.setStringValue_("✓ " + i18n.t("settings_saved_b"))
        except Exception:
            self._set_saved.setStringValue_(i18n.t("upd_fail_t"))

    @objc.python_method
    def _change_path(self):
        core = self.core
        p = core.choose_folder()
        if not p or not core.set_vault(p):
            return
        self._set_path_val.setStringValue_(str(core.VAULT))
        try:
            self.app.vault_item.title = self.app._vault_title()
        except Exception:
            pass
        if self._cur == "home":
            self._refresh_home()

    # ======================================================================
    #  关于 / 介绍
    # ======================================================================
    @objc.python_method
    def _build_about(self):
        cw, ch = CONTENT_W, WIN_H
        core = self.core
        v = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, cw, ch))
        PAD = 40
        v.addSubview_(make_rich_label(
            NSMakeRect(PAD, ch - 96, cw - 2 * PAD, 64),
            [(i18n.t("app_name") + "\n", title_font(30), C_PRIMARY()),
             (i18n.t("about_tagline"), body_font(13), C_SECONDARY())]))
        v.addSubview_(_text(NSMakeRect(PAD, ch - 124, cw - 2 * PAD, 18),
                            i18n.t("cur_version", app=i18n.t("app_name"), v=core.VERSION),
                            body_font(12), C_TERTIARY()))
        v.addSubview_(_separator(PAD, ch - 144, cw - 2 * PAD))
        v.addSubview_(make_rich_label(
            NSMakeRect(PAD, ch - 144 - 200, cw - 2 * PAD, 190),
            [(i18n.t("about_intro"), body_font(13.5), C_PRIMARY())]))
        # 底部：检查更新 + 作者链接
        y = 36
        v.addSubview_(_btn(NSMakeRect(PAD, y, 150, 32), i18n.t("about_check_btn"),
                           lambda: self.app.do_update(None), self._retain))
        v.addSubview_(_btn(NSMakeRect(PAD + 162, y, 130, 32), i18n.t("about_home_btn"),
                           lambda: self.app.open_homepage(None), self._retain))
        v.addSubview_(_btn(NSMakeRect(PAD + 162 + 140, y, 130, 32), i18n.t("about_obsidian_btn"),
                           lambda: self.app.open_vault_site(None), self._retain))
        v.addSubview_(_btn(NSMakeRect(PAD + 162 + 280, y, 130, 32), "GitHub",
                           lambda: self.app.open_github(None), self._retain))
        return v
