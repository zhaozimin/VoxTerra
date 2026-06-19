#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 AppKit(PyObjC) 的 NSWindow/NSTextView/NSProgressIndicator/NSApp 等；依赖 ui_common 的 BtnTarget/make_label/make_rich_label/字体颜色
[OUTPUT]: 对外提供 EnrollWindow 类(两阶段：须知→开始→采集；update/finish/close)
[POS]: voicelog 的声纹注册 UI 面(PyObjC/Cocoa)。两阶段引导：先「须知页」(本地/隐私说明 + 开始按钮，不录音)，
       用户点「开始」后才切到「朗读页」并正式开始录音。纯展示层，采集逻辑在主文件 Recorder.enroll，进度由 rumps.Timer 喂。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

为什么两阶段：弹窗即录会让用户没反应过来。先须知后开始，既给用户准备时间，又用「用户须知」打消隐私顾虑。
菜单栏附件型 App 弹窗需临时切 Regular 策略(变前台)才能稳被看见与交互，关窗再切回 Accessory(无 Dock)。
所有 AppKit 操作必须在主线程(rumps 菜单回调 / rumps.Timer)调用。
"""
from AppKit import (
    NSWindow, NSTextView, NSScrollView, NSProgressIndicator, NSButton, NSFont,
    NSMakeRect, NSMakeSize, NSWindowStyleMaskTitled, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSBezelBorder,
)

from ui_common import (
    BtnTarget, make_label, make_rich_label, title_font, C_PRIMARY,
    push_regular, pop_regular,
)
import i18n

_BIG = 1.0e7


# ============================================================================
#  声纹注册窗口：两阶段。intro(须知 + 开始) → capture(朗读 + 进度)。
#  所有方法防御式 try/except——注册 UI 不能拖垮常驻录音进程。
# ============================================================================
class EnrollWindow:
    def __init__(self, intro_text: str, script: str, on_start=None, on_cancel=None):
        self._script = script
        self._on_start = on_start
        self._on_cancel = on_cancel
        self._finished = False
        self._phase = "intro"
        W, H = 720, 600
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), NSWindowStyleMaskTitled,  # 不加 Closable：只走我们的按钮，生命周期可控
            NSBackingStoreBuffered, False)
        win.setTitle_(i18n.t("enroll_win_title"))
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        self.win = win
        c = win.contentView()

        self.header = make_rich_label(
            NSMakeRect(24, H - 58, W - 48, 38),
            [(i18n.t("enroll_win_title"), title_font(15), C_PRIMARY())])
        c.addSubview_(self.header)

        # 文本区：须知 / 朗读稿复用同一控件，切阶段时换内容与字号
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 116, W - 48, H - 176))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 48, H - 176))
        tv.setEditable_(False)
        tv.setSelectable_(False)
        tv.setTextContainerInset_(NSMakeSize(18, 16))
        tv.setFont_(NSFont.systemFontOfSize_(14))   # 须知用 14pt
        tv.setString_(intro_text)
        scroll.setDocumentView_(tv)
        self.tv = tv
        c.addSubview_(scroll)

        # 进度条 + 状态：采集阶段才显示
        bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(24, 86, W - 48, 18))
        bar.setIndeterminate_(False)
        bar.setMinValue_(0.0)
        bar.setMaxValue_(1.0)
        bar.setDoubleValue_(0.0)
        bar.setHidden_(True)
        self.bar = bar
        c.addSubview_(bar)

        self.status = make_label(NSMakeRect(24, 54, W - 300, 24), "", 13)
        self.status.setHidden_(True)
        c.addSubview_(self.status)

        cancel = NSButton.alloc().initWithFrame_(NSMakeRect(W - 260, 16, 110, 34))
        cancel.setTitle_(i18n.t("cancel"))
        cancel.setBezelStyle_(1)
        cancel.setKeyEquivalent_("\x1b")   # Esc = 取消（永远有键盘退路）
        self._t_cancel = BtnTarget.alloc().initWithCallback_(self._cancel)
        cancel.setTarget_(self._t_cancel)
        cancel.setAction_("invoke:")
        c.addSubview_(cancel)

        start = NSButton.alloc().initWithFrame_(NSMakeRect(W - 140, 16, 110, 34))
        start.setTitle_(i18n.t("start"))
        start.setBezelStyle_(1)
        start.setKeyEquivalent_("\r")   # 回车=开始
        self._t_start = BtnTarget.alloc().initWithCallback_(self._begin)
        start.setTarget_(self._t_start)
        start.setAction_("invoke:")
        self.start_btn = start
        c.addSubview_(start)

        win.makeKeyAndOrderFront_(None)
        push_regular()   # 作为构造最后一步：前置 AppKit 调用都成功后才切前台，失败则不会卡住 Dock 图标

    # ---------------- 阶段切换：须知 → 采集 ----------------
    def _begin(self):
        if self._phase != "intro":
            return
        self._phase = "capture"
        try:
            self.tv.setFont_(NSFont.systemFontOfSize_(20))  # 朗读用大字
            self.tv.setString_(self._script)
            self.start_btn.setHidden_(True)
            self.bar.setHidden_(False)
            self.status.setHidden_(False)
            self.status.setStringValue_(i18n.t("prepare"))
        except Exception:
            pass
        if self._on_start:
            try:
                self._on_start()
            except Exception:
                self._cancel()   # 启动失败别留下没有进度、无法收尾的僵尸采集窗

    def _cancel(self):
        if self._on_cancel:
            self._on_cancel()
        self.close()

    # ---------------- 由主线程的 rumps.Timer 调用 ----------------
    def update(self, progress: float, voiced: float, target: float, elapsed: int):
        try:
            self.bar.setDoubleValue_(float(progress))
            self.status.setStringValue_(i18n.t(
                "progress", v=f"{voiced:.1f}", t=f"{target:.0f}",
                p=round(progress * 100), e=elapsed))
        except Exception:
            pass

    def finish(self, ok: bool, msg: str):
        self._finished = True
        try:
            if ok:
                self.bar.setDoubleValue_(1.0)
            self.status.setHidden_(False)
            self.status.setStringValue_(msg)
            self.start_btn.setHidden_(True)
        except Exception:
            pass

    def close(self):
        if getattr(self, "_closed", False):
            return                       # 幂等：取消/自动收尾可能都来关，只 pop 一次
        self._closed = True
        try:
            self.win.orderOut_(None)
            self.win.close()
        except Exception:
            pass
        pop_regular()                    # 计数归零才切回无 Dock 菜单栏状态
