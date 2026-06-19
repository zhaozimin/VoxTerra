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

from ui_common import (
    BtnTarget, make_rich_label, title_font, body_font,
    C_PRIMARY, C_SECONDARY, C_TERTIARY, push_regular, pop_regular,
)
import i18n

_BIG = 1.0e7  # 文本容器"无限高"，配合可垂直增长的 textview


# ============================================================================
#  关键词管理窗口(模态)：可编辑文本框 + 保存/取消。
# ============================================================================
class ReplaceWindow:
    def __init__(self, initial_text: str):
        self._result = "cancel"
        W, H = 600, 600
        win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), NSWindowStyleMaskTitled,  # 不加 Closable：避免红叉关闭绕过 stopModal
            NSBackingStoreBuffered, False)
        win.setTitle_(i18n.t("kw_win_title"))
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        self.win = win
        c = win.contentView()

        c.addSubview_(make_rich_label(
            NSMakeRect(24, H - 152, W - 48, 132),
            [(i18n.t("kw_h_title") + "\n", title_font(15), C_PRIMARY()),
             (i18n.t("kw_h_sub") + "\n\n", body_font(12), C_SECONDARY()),
             (i18n.t("kw_h_r1a"), body_font(13), C_PRIMARY()),
             (i18n.t("kw_h_r1b") + "\n", body_font(12), C_SECONDARY()),
             (i18n.t("kw_h_r2a"), body_font(13), C_PRIMARY()),
             (i18n.t("kw_h_r2b") + "\n", body_font(12), C_SECONDARY()),
             (i18n.t("kw_h_eg"), body_font(11), C_TERTIARY())]))

        # 可编辑文本框(正确配置容器，编辑/换行/滚动才正常)
        scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(24, 72, W - 48, H - 244))
        scroll.setHasVerticalScroller_(True)
        scroll.setBorderType_(NSBezelBorder)
        tv = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, W - 48, H - 244))
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
        tv.textContainer().setContainerSize_(NSMakeSize(W - 48, _BIG))
        tv.textContainer().setWidthTracksTextView_(True)
        tv.setString_(initial_text)
        scroll.setDocumentView_(tv)
        self.tv = tv
        c.addSubview_(scroll)

        cancel = NSButton.alloc().initWithFrame_(NSMakeRect(W - 260, 20, 110, 34))
        cancel.setTitle_(i18n.t("cancel"))
        cancel.setBezelStyle_(1)
        cancel.setKeyEquivalent_("\x1b")   # Esc = 取消
        self._t_cancel = BtnTarget.alloc().initWithCallback_(self._cancel)
        cancel.setTarget_(self._t_cancel)
        cancel.setAction_("invoke:")
        c.addSubview_(cancel)

        save = NSButton.alloc().initWithFrame_(NSMakeRect(W - 140, 20, 110, 34))
        save.setTitle_(i18n.t("save"))
        save.setBezelStyle_(1)
        self._t_save = BtnTarget.alloc().initWithCallback_(self._save)
        save.setTarget_(self._t_save)
        save.setAction_("invoke:")
        c.addSubview_(save)

    # ---------------- 模态运行：返回 (result, text) ----------------
    def run_modal(self):
        # 菜单栏 App 默认 Accessory 策略下，窗口能显示但键盘被送给真正前台 App→只能看不能打字。
        # push_regular() 变前台夺回键盘；try/finally 保证无论如何都 pop 回去，不卡 Dock 图标。
        push_regular()
        text = ""
        try:
            self.win.makeKeyAndOrderFront_(None)
            self.win.makeFirstResponder_(self.tv)   # 光标进文本框，键盘直达
            NSApp.runModalForWindow_(self.win)       # 阻塞至 stopModal
            text = self.tv.string()
        except Exception:
            pass
        finally:
            try:
                self.win.orderOut_(None)
                self.win.close()
            except Exception:
                pass
            pop_regular()
        return self._result, text

    def _save(self):
        self._result = "save"
        NSApp.stopModal()

    def _cancel(self):
        self._result = "cancel"
        NSApp.stopModal()
