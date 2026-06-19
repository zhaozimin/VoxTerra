#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 AppKit(PyObjC) 的 NSWindow/NSTextView/NSApp 等；依赖 ui_common 的 BtnTarget/make_label
[OUTPUT]: 对外提供 ReplaceWindow 类(run_modal() -> (result, text))
[POS]: voicelog 的「关键词管理 UI 面」。一个可编辑文本框承载两类规则(每行 `错=正` 精确纠错 / 单写目标词
       入识别词库)；增删改批量都在这一个面里。模态运行——菜单栏附件型 App 唯有模态窗口能稳拿键盘焦点。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

为什么模态：rumps 是 LSUIElement(无 Dock) 进程，非模态窗口常拿不到键盘焦点→只能看不能打字。
runModalForWindow 像系统弹窗一样强制激活并把按键路由到本窗口，是可靠的文本输入方式。
所有 AppKit 操作必须在主线程(rumps 菜单回调)调用。
"""
from AppKit import (
    NSWindow, NSTextView, NSScrollView, NSButton, NSApp, NSFont,
    NSMakeRect, NSMakeSize, NSWindowStyleMaskTitled, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSBezelBorder, NSViewWidthSizable,
)

from ui_common import BtnTarget, make_label

_BIG = 1.0e7  # 文本容器"无限高"，配合可垂直增长的 textview


# ============================================================================
#  关键词管理窗口(模态)：可编辑文本框 + 保存/取消。
# ============================================================================
class ReplaceWindow:
    def __init__(self, initial_text: str):
        self._result = "cancel"
        W, H = 600, 560
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), NSWindowStyleMaskTitled,  # 不加 Closable：避免红叉关闭绕过 stopModal
            NSBackingStoreBuffered, False)
        win.setTitle_("关键词纠错")
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        self.win = win
        c = win.contentView()

        c.addSubview_(make_label(
            NSMakeRect(20, H - 116, W - 40, 96),
            "每行一条，保存即时生效：\n"
            "  错词 = 正词   →  精确纠错：转写出现「错词」就替换成「正词」\n"
            "  目标词         →  识别词库：让 Whisper 更可能直接听对它（从源头减少错认）\n"
            "例：  克劳德 = Claude       或只写       Obsidian", 13))

        # 可编辑文本框(正确配置容器，编辑/换行/滚动才正常)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(20, 70, W - 40, H - 200))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 40, H - 200))
        tv.setEditable_(True)
        tv.setSelectable_(True)
        tv.setRichText_(False)
        tv.setFont_(NSFont.userFixedPitchFontOfSize_(15) or NSFont.systemFontOfSize_(15))
        tv.setTextContainerInset_(NSMakeSize(10, 10))
        tv.setMinSize_(NSMakeSize(0.0, 0.0))
        tv.setMaxSize_(NSMakeSize(_BIG, _BIG))
        tv.setVerticallyResizable_(True)
        tv.setHorizontallyResizable_(False)
        tv.setAutoresizingMask_(NSViewWidthSizable)
        tv.textContainer().setContainerSize_(NSMakeSize(W - 40, _BIG))
        tv.textContainer().setWidthTracksTextView_(True)
        tv.setString_(initial_text)
        scroll.setDocumentView_(tv)
        self.tv = tv
        c.addSubview_(scroll)

        cancel = NSButton.alloc().initWithFrame_(NSMakeRect(W - 260, 20, 110, 34))
        cancel.setTitle_("取消")
        cancel.setBezelStyle_(1)
        self._t_cancel = BtnTarget.alloc().initWithCallback_(self._cancel)
        cancel.setTarget_(self._t_cancel)
        cancel.setAction_("invoke:")
        c.addSubview_(cancel)

        save = NSButton.alloc().initWithFrame_(NSMakeRect(W - 140, 20, 110, 34))
        save.setTitle_("保存")
        save.setBezelStyle_(1)
        self._t_save = BtnTarget.alloc().initWithCallback_(self._save)
        save.setTarget_(self._t_save)
        save.setAction_("invoke:")
        c.addSubview_(save)

    # ---------------- 模态运行：返回 (result, text) ----------------
    def run_modal(self):
        NSApp.activateIgnoringOtherApps_(True)
        self.win.makeKeyAndOrderFront_(None)
        self.win.makeFirstResponder_(self.tv)   # 让光标进文本框，键盘直达
        NSApp.runModalForWindow_(self.win)       # 阻塞至 stopModal
        text = ""
        try:
            text = self.tv.string()
        except Exception:
            pass
        try:
            self.win.orderOut_(None)
            self.win.close()
        except Exception:
            pass
        return self._result, text

    def _save(self):
        self._result = "save"
        NSApp.stopModal()

    def _cancel(self):
        self._result = "cancel"
        NSApp.stopModal()
