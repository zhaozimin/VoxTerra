#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 AppKit/Foundation(PyObjC，rumps 已带入) 的 NSWindow/NSTextView/NSProgressIndicator 等
[OUTPUT]: 对外提供 EnrollWindow 类(update/finish/close) 与 ok_quality 阈值
[POS]: voicelog 的「声纹注册 UI 面」——取代 TextEdit，提供统一排版的朗读稿 + 实时进度条 + 提取质量反馈。
       纯展示层：自身不碰音频，只读 voicelog_menubar 写进 state 的进度数字并渲染；采集逻辑在 Recorder.enroll。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

为什么自建窗口：TextEdit 的字体/排版每台机器都不同、且无法显示进度与采集质量。我们需要一块自己拥有、
可控、可实时刷新的面。所有 AppKit 操作必须在主线程调用（由 rumps 菜单回调 / rumps.Timer 保证）。
"""
import objc
from AppKit import (
    NSWindow, NSTextField, NSTextView, NSScrollView, NSProgressIndicator,
    NSButton, NSApp, NSFont, NSMakeRect, NSMakeSize,
    NSWindowStyleMaskTitled, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSBezelBorder,
)
from Foundation import NSObject


# ============================================================================
#  按钮回调桥：AppKit 按钮需要一个 ObjC target，转调 Python 回调。
# ============================================================================
class _BtnTarget(NSObject):
    def initWithCallback_(self, cb):
        self = objc.super(_BtnTarget, self).init()
        if self is None:
            return None
        self._cb = cb
        return self

    def invoke_(self, sender):
        try:
            if self._cb:
                self._cb()
        except Exception:
            pass


# ============================================================================
#  声纹注册窗口：朗读稿(大字、统一) + 进度条(按有效语音量) + 状态行 + 取消/关闭。
#  全部方法防御式 try/except——注册 UI 再怎么样也不能拖垮常驻录音进程。
# ============================================================================
class EnrollWindow:
    def __init__(self, script: str, on_cancel=None):
        self.on_cancel = on_cancel
        self._finished = False
        W, H = 720, 600
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), NSWindowStyleMaskTitled, NSBackingStoreBuffered, False)
        win.setTitle_("声纹注册 · 朗读以下内容")
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        self.win = win
        c = win.contentView()

        c.addSubview_(self._label(
            NSMakeRect(20, 555, W - 40, 28),
            "请用平常聊天的语气自然朗读（中英文都念到）；采够音色会自动停止，不必盯着时间。", 13))

        # 朗读稿(只读、可滚动、统一 20pt 系统字体)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 120, W - 40, 420))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 40, 420))
        tv.setEditable_(False)
        tv.setSelectable_(False)
        tv.setFont_(NSFont.systemFontOfSize_(20))
        tv.setTextContainerInset_(NSMakeSize(16, 16))
        tv.setString_(script)
        scroll.setDocumentView_(tv)
        c.addSubview_(scroll)

        # 进度条(0~1，按「有效语音」累计)
        bar = NSProgressIndicator.alloc().initWithFrame_(NSMakeRect(20, 88, W - 40, 18))
        bar.setIndeterminate_(False)
        bar.setMinValue_(0.0)
        bar.setMaxValue_(1.0)
        bar.setDoubleValue_(0.0)
        self.bar = bar
        c.addSubview_(bar)

        self.status = self._label(NSMakeRect(20, 54, W - 280, 26), "准备中…", 14)
        c.addSubview_(self.status)

        btn = NSButton.alloc().initWithFrame_(NSMakeRect(W - 140, 48, 120, 32))
        btn.setTitle_("取消")
        btn.setBezelStyle_(1)  # rounded
        self._btn_target = _BtnTarget.alloc().initWithCallback_(self._on_btn)
        btn.setTarget_(self._btn_target)
        btn.setAction_("invoke:")
        self.btn = btn
        c.addSubview_(btn)

        NSApp.activateIgnoringOtherApps_(True)
        win.makeKeyAndOrderFront_(None)

    @staticmethod
    def _label(frame, text, size):
        lbl = NSTextField.alloc().initWithFrame_(frame)
        lbl.setStringValue_(text)
        lbl.setEditable_(False)
        lbl.setSelectable_(False)
        lbl.setBezeled_(False)
        lbl.setDrawsBackground_(False)
        lbl.setFont_(NSFont.systemFontOfSize_(size))
        return lbl

    def _on_btn(self):
        if self._finished:
            self.close()
        else:
            if self.on_cancel:
                self.on_cancel()
            try:
                self.status.setStringValue_("正在取消…")
            except Exception:
                pass

    # ---------------- 由主线程的 rumps.Timer 调用 ----------------
    def update(self, progress: float, voiced: float, target: float, elapsed: int):
        try:
            self.bar.setDoubleValue_(float(progress))
            self.status.setStringValue_(
                f"已采集有效语音 {voiced:.1f} / {target:.0f} 秒（{round(progress*100)}%）· 用时 {elapsed}s · 请继续朗读")
        except Exception:
            pass

    def finish(self, ok: bool, msg: str):
        self._finished = True
        try:
            if ok:
                self.bar.setDoubleValue_(1.0)
            self.status.setStringValue_(msg)
            self.btn.setTitle_("关闭")
        except Exception:
            pass

    def close(self):
        try:
            self.win.orderOut_(None)
            self.win.close()
        except Exception:
            pass
