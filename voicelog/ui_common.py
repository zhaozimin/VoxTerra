#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 AppKit/Foundation(PyObjC，rumps 已带入) 的 NSWindow/NSObject/NSTextField/NSFont/NSEvent 修饰键常量
[OUTPUT]: 对外提供 KeyWindow(补回编辑快捷键的模态窗基类)、BtnTarget(按钮回调桥)、make_label/make_rich_label(只读标签)、push_regular/pop_regular/floor_regular(前台策略计数·V1 常驻 Dock)、字体颜色 helper
[POS]: voicelog 各原生窗口(enroll_ui / replace_ui)的公共底座，消除按钮桥与标签的重复代码。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md

所有 AppKit 操作必须在主线程调用(由 rumps 菜单回调 / rumps.Timer 保证)。
"""
import objc
from AppKit import (
    NSWindow, NSTextField, NSFont, NSColor, NSApp,
    NSMutableParagraphStyle, NSFontAttributeName,
    NSForegroundColorAttributeName, NSParagraphStyleAttributeName,
    NSApplicationActivationPolicyRegular, NSApplicationActivationPolicyAccessory,
    NSEventModifierFlagCommand, NSEventModifierFlagShift,
)
from Foundation import NSObject, NSAttributedString, NSMutableAttributedString


# ============================================================================
#  激活策略（前台/菜单栏）引用计数：多个窗口可能同时需要前台。
#  菜单栏 App 默认 Accessory(无 Dock)下窗口拿不到键盘/不稳前台 → 开窗 push_regular(变前台)，
#  关窗 pop_regular()；只有计数归零才切回 Accessory。避免两窗各自盲切互相踩、或失败路径卡住 Dock 图标。
# ============================================================================
_regular_depth = 0


def push_regular():
    global _regular_depth
    _regular_depth += 1
    if _regular_depth == 1:
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        except Exception:
            pass
    try:
        NSApp.activateIgnoringOtherApps_(True)
    except Exception:
        pass


def pop_regular():
    global _regular_depth
    _regular_depth = max(0, _regular_depth - 1)
    if _regular_depth == 0:
        try:
            NSApp.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
        except Exception:
            pass


def floor_regular():
    """全窗口产品(V1)：把激活策略钉为 Regular(常驻 Dock)。给引用计数垫一层永久底,
    使后续模态子窗(注册/设置/关键词)的 push/pop 永不把 App 切回无 Dock 的 Accessory。
    幂等——多次调用只垫一次。lite 形态不调它，行为完全不变。"""
    global _regular_depth, _floored
    if _floored:
        return
    _floored = True
    _regular_depth += 1
    try:
        NSApp.setActivationPolicy_(NSApplicationActivationPolicyRegular)
        NSApp.activateIgnoringOtherApps_(True)
    except Exception:
        pass


_floored = False


# ============================================================================
#  可编辑模态窗口：补回标准编辑快捷键(Cmd+X/C/V/A/Z)。
#  LSUIElement App 无主菜单 → 系统没人把 Cmd+V 翻成 paste: 动作 → 文本框收不到粘贴。
#  在窗口层拦截命令键，转发给第一响应者(文本框)。此路径有 Esc 按钮佐证：模态循环里
#  NSWindow.performKeyEquivalent_ 确被调用。命中即吞，未命中(sendAction 返回假)落回 super，
#  按钮的 Esc/回车等价物照常工作。一处子类，所有文本输入窗复用。
# ============================================================================
_EDIT_SEL = {"x": "cut:", "c": "copy:", "v": "paste:", "a": "selectAll:", "z": "undo:"}


class KeyWindow(NSWindow):
    def performKeyEquivalent_(self, event):
        if event.modifierFlags() & NSEventModifierFlagCommand:
            ch = (event.charactersIgnoringModifiers() or "").lower()
            sel = _EDIT_SEL.get(ch)
            if ch == "z" and (event.modifierFlags() & NSEventModifierFlagShift):
                sel = "redo:"   # Cmd+Shift+Z = 重做
            if sel:
                # 一级：直投本窗口第一响应者(焦点文本框)。剪贴板四件套(剪切/复制/粘贴/全选)
                # 文本框自身即应答，不依赖 key window 状态——performKeyEquivalent_ 正由持有焦点的本窗口调用。
                r = self.firstResponder()
                if r is not None and r.respondsToSelector_(sel):
                    r.performSelector_withObject_(sel, None)   # sender=nil:标准编辑动作不关心来源
                    return True
                # 二级：撤销/重做(undo:/redo:)文本框不直接应答，落回完整响应者链至 undo manager。
                if NSApp.sendAction_to_from_(sel, None, self):
                    return True
        return objc.super(KeyWindow, self).performKeyEquivalent_(event)


# ============================================================================
#  按钮回调桥：AppKit 按钮需要一个 ObjC target，转调 Python 回调。
#  用法：t = BtnTarget.alloc().initWithCallback_(cb); btn.setTarget_(t); btn.setAction_("invoke:")
#  注意：必须用 python 变量持有 target，否则被 GC 后点击无反应。
# ============================================================================
class BtnTarget(NSObject):
    def initWithCallback_(self, cb):
        self = objc.super(BtnTarget, self).init()
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


def make_label(frame, text: str, size: float):
    """只读、无边框、透明背景的文字标签。"""
    lbl = NSTextField.alloc().initWithFrame_(frame)
    lbl.setStringValue_(text)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setFont_(NSFont.systemFontOfSize_(size))
    return lbl


# 语义字体/颜色：用「层次」代替「一坨等宽文本」，避免廉价感。
def title_font(size=15.0):
    return NSFont.boldSystemFontOfSize_(size)


def body_font(size=12.5):
    return NSFont.systemFontOfSize_(size)


def C_PRIMARY():    return NSColor.labelColor()
def C_SECONDARY():  return NSColor.secondaryLabelColor()
def C_TERTIARY():   return NSColor.tertiaryLabelColor()


def make_rich_label(frame, segments, line_spacing=5.0, para_spacing=6.0):
    """富文本多行只读标签。segments: [(text, font, color|None), ...]，拼成带行距的层次化标题块。"""
    s = NSMutableAttributedString.alloc().init()
    for text, font, color in segments:
        attrs = {NSFontAttributeName: font}
        if color is not None:
            attrs[NSForegroundColorAttributeName] = color
        s.appendAttributedString_(
            NSAttributedString.alloc().initWithString_attributes_(text, attrs))
    ps = NSMutableParagraphStyle.alloc().init()
    ps.setLineSpacing_(line_spacing)
    ps.setParagraphSpacing_(para_spacing)
    s.addAttribute_value_range_(NSParagraphStyleAttributeName, ps, (0, s.length()))

    lbl = NSTextField.alloc().initWithFrame_(frame)
    lbl.setEditable_(False)
    lbl.setSelectable_(False)
    lbl.setBezeled_(False)
    lbl.setDrawsBackground_(False)
    lbl.setUsesSingleLineMode_(False)
    lbl.cell().setWraps_(True)
    lbl.setAttributedStringValue_(s)
    return lbl
