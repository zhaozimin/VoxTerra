#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[INPUT]: 依赖 AppKit(PyObjC) 的 NSSlider/NSTextField/NSButton/NSView/NSBezierPath 等；依赖 ui_common 的
         KeyWindow/BtnTarget/make_rich_label/字体颜色/push_regular/pop_regular
[OUTPUT]: 对外提供 SettingsWindow(current).run_modal()->(result, vals)、make_param_card(单卡工厂)、
          read_card_values(读卡)、PARAMS/DEFAULTS/CARD_H/_quantize/_fmt
[POS]: voicelog 的「参数设置 UI 面」。门控阈值做成 卡片式 滑块+可编辑数字框+范围+越小/越大说明。
       一参数一卡片(圆角底色块+间距)。卡片工厂 make_param_card 是单一真相源——
       模态设置窗(本文件 SettingsWindow)与全窗口产品的「设置」页(main_window)共用它,绝不重复造卡。
       模态——菜单栏附件型 App 唯有模态窗口能稳拿键盘焦点(数字框可输入)。
[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
"""
import objc
from Foundation import NSObject
from AppKit import (
    NSView, NSSlider, NSTextField, NSButton, NSApp, NSFont, NSColor, NSBezierPath,
    NSMakeRect, NSWindowStyleMaskTitled, NSBackingStoreBuffered,
    NSFloatingWindowLevel, NSTextAlignmentRight,
)

from ui_common import (
    KeyWindow, BtnTarget, make_rich_label, title_font, body_font,
    C_PRIMARY, C_SECONDARY, C_TERTIARY, push_regular, pop_regular,
)
import i18n

# ============================================================================
#  参数规格：(key, 名称, min, max, step, 默认, 整数?, 越小说明, 越大说明)
# ============================================================================
PARAMS = [
    ("vad_threshold",          "切句灵敏度  vad_threshold",          0.30, 0.90, 0.05,  0.60, False,
     "越小越易开句(噪声易误触)", "越大越严(轻声可能漏)"),
    ("min_speech_ms",          "最短句长  min_speech_ms",            100,  1000, 50,    300,  True,
     "越小短噪声易进",          "越大短句被丢"),
    ("min_silence_ms",         "停顿断句  min_silence_ms",           300,  1500, 50,    700,  True,
     "越小切得碎",              "越大合成长句"),
    ("min_rms_dbfs",           "近场响度门  min_rms_dbfs",           -60,  -30,  1,     -45,  False,
     "越小(更负)收得越远(易混外放)", "越大只收很近的响声"),
    ("speaker_threshold",      "声纹严格度  speaker_threshold",      0.10, 0.80, 0.01,  0.35, False,
     "越小越宽松(可能混入他人)", "越大越严(可能误丢你)"),
    ("speaker_min_verify_sec", "短句豁免时长  speaker_min_verify_sec", 0.0, 3.0,  0.1,   1.2,  False,
     "越小更多短句也验声纹",    "越大更多短句直接放行"),
    ("max_utterance_sec",      "单句上限  max_utterance_sec",        10,   60,   5,     30,   True,
     "越小切得勤",              "越大允许长段"),
]
DEFAULTS = {p[0]: p[5] for p in PARAMS}


def _fmt(spec, val):
    _, _, lo, hi, step, _, is_int, *_ = spec
    if is_int:
        return str(int(round(val)))
    return f"{val:.2f}" if step < 0.05 else f"{val:.1f}"


def _quantize(spec, val):
    _, _, lo, hi, step, _, is_int, *_ = spec
    val = max(lo, min(hi, val))
    val = round((val - lo) / step) * step + lo
    return int(round(val)) if is_int else round(val, 4)


def _label(frame, text, font, color):
    t = NSTextField.alloc().initWithFrame_(frame)
    t.setStringValue_(text); t.setBezeled_(False); t.setEditable_(False); t.setDrawsBackground_(False)
    t.setFont_(font); t.setTextColor_(color)
    return t


# ---------------- 卡片：圆角底色块,把一个参数的所有控件框成独立一块 ----------------
class CardView(NSView):
    def drawRect_(self, dirty):
        p = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 10.0, 10.0)
        NSColor.controlBackgroundColor().setFill(); p.fill()
        NSColor.separatorColor().setStroke(); p.setLineWidth_(1.0); p.stroke()


class _Tgt(NSObject):
    def initWithCb_(self, cb):
        self = objc.super(_Tgt, self).init()
        self._cb = cb
        return self

    def act_(self, sender):
        self._cb(sender)


# ============================================================================
#  卡片工厂（单一真相源）：造「名称 + 滑块 + 可编辑数字框 + 范围 + 越小/越大说明」一张卡。
#  模态设置窗与全窗口产品的设置页都调它——双向同步(滑块↔数字框),改一处两处都对。
#  卡片以原点 (0,0) 创建,由调用方 setFrameOrigin_ 摆位；ObjC target 追加进 retain 防 GC。
# ============================================================================
CARD_H, CARD_GAP = 72, 10


def make_param_card(spec, cur, CW, retain):
    """造一张参数卡,返回 (card, slider, field)。retain: 调用方持有的列表,本函数把 ObjC target 塞进去。"""
    key, name, lo, hi, step, default, is_int, hint_lo, hint_hi = spec
    card = CardView.alloc().initWithFrame_(NSMakeRect(0, 0, CW, CARD_H))
    card.addSubview_(_label(NSMakeRect(16, CARD_H - 26, CW - 150, 18), name, title_font(13), C_PRIMARY()))
    fld = NSTextField.alloc().initWithFrame_(NSMakeRect(CW - 90, CARD_H - 27, 74, 22))
    fld.setStringValue_(_fmt(spec, cur)); fld.setAlignment_(NSTextAlignmentRight)
    fld.setFont_(NSFont.userFixedPitchFontOfSize_(12) or NSFont.systemFontOfSize_(12))
    sld = NSSlider.alloc().initWithFrame_(NSMakeRect(16, 26, CW - 170, 20))
    sld.setMinValue_(float(lo)); sld.setMaxValue_(float(hi)); sld.setDoubleValue_(float(cur))
    sld.setContinuous_(True)
    ts = _Tgt.alloc().initWithCb_(
        lambda s, sp=spec, f=fld: f.setStringValue_(_fmt(sp, _quantize(sp, s.doubleValue()))))
    sld.setTarget_(ts); sld.setAction_("act:")

    def _field_changed(f, sp=spec, s=sld):
        try:
            v = _quantize(sp, float(f.stringValue()))
        except Exception:
            v = _quantize(sp, s.doubleValue())
        s.setDoubleValue_(float(v)); f.setStringValue_(_fmt(sp, v))
    tf = _Tgt.alloc().initWithCb_(_field_changed)
    fld.setTarget_(tf); fld.setAction_("act:")

    card.addSubview_(_label(NSMakeRect(CW - 150, 28, 134, 16),
                            f"范围 {_fmt(spec, lo)}–{_fmt(spec, hi)}", body_font(10.5), C_TERTIARY()))
    card.addSubview_(_label(NSMakeRect(16, 6, CW - 32, 15),
                            f"← {hint_lo}　｜　{hint_hi} →", body_font(10.5), C_SECONDARY()))
    card.addSubview_(fld); card.addSubview_(sld)
    retain += [ts, tf]
    return card, sld, fld


def read_card_values(rows):
    """从 [(spec, slider, field), ...] 读出 {key: 量化值}——数字框优先,解析失败回落滑块。"""
    vals = {}
    for spec, sld, fld in rows:
        try:
            v = _quantize(spec, float(fld.stringValue()))
        except Exception:
            v = _quantize(spec, sld.doubleValue())
        vals[spec[0]] = v
    return vals


# ============================================================================
#  设置窗口(模态)：一参数一卡片，垂直堆叠。卡片本体由 make_param_card 统一产出。
# ============================================================================
class SettingsWindow:
    def __init__(self, current: dict):
        self._result = "cancel"
        self._rows = []          # [(spec, slider, field), ...]
        self._targets = []       # 持有 ObjC target,防 GC
        W = 600
        SIDE = 24
        CW = W - 2 * SIDE        # 卡片宽
        CH, GAP = CARD_H, CARD_GAP
        top_pad, hdr, btn_h = 16, 46, 64
        n = len(PARAMS)
        H = top_pad + hdr + n * CH + (n - 1) * GAP + 18 + btn_h
        win = KeyWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, W, H), NSWindowStyleMaskTitled, NSBackingStoreBuffered, False)
        win.setTitle_(i18n.t("settings_title"))
        win.setLevel_(NSFloatingWindowLevel)
        win.center()
        self.win = win
        c = win.contentView()

        c.addSubview_(make_rich_label(
            NSMakeRect(SIDE, H - top_pad - hdr, CW, hdr),
            [(i18n.t("settings_title") + "\n", title_font(15), C_PRIMARY()),
             (i18n.t("settings_sub"), body_font(11), C_SECONDARY())]))

        card_top = H - top_pad - hdr - GAP
        for i, spec in enumerate(PARAMS):
            cur = current.get(spec[0], spec[5])
            top = card_top - i * (CH + GAP)
            card, sld, fld = make_param_card(spec, cur, CW, self._targets)
            card.setFrameOrigin_((SIDE, top - CH))
            c.addSubview_(card)
            self._rows.append((spec, sld, fld))

        reset = NSButton.alloc().initWithFrame_(NSMakeRect(SIDE, 18, 120, 32))
        reset.setTitle_(i18n.t("settings_reset")); reset.setBezelStyle_(1)
        self._t_reset = BtnTarget.alloc().initWithCallback_(self._reset)
        reset.setTarget_(self._t_reset); reset.setAction_("invoke:")
        c.addSubview_(reset)
        cancel = NSButton.alloc().initWithFrame_(NSMakeRect(W - 250, 18, 110, 32))
        cancel.setTitle_(i18n.t("cancel")); cancel.setBezelStyle_(1); cancel.setKeyEquivalent_("\x1b")
        self._t_cancel = BtnTarget.alloc().initWithCallback_(self._cancel)
        cancel.setTarget_(self._t_cancel); cancel.setAction_("invoke:")
        c.addSubview_(cancel)
        save = NSButton.alloc().initWithFrame_(NSMakeRect(W - 130, 18, 110, 32))
        save.setTitle_(i18n.t("save")); save.setBezelStyle_(1)
        self._t_save = BtnTarget.alloc().initWithCallback_(self._save)
        save.setTarget_(self._t_save); save.setAction_("invoke:")
        c.addSubview_(save)

    def run_modal(self):
        push_regular()
        vals = {}
        try:
            self.win.makeKeyAndOrderFront_(None)
            NSApp.runModalForWindow_(self.win)
            if self._result == "save":
                vals = read_card_values(self._rows)
        except Exception:
            pass
        finally:
            try:
                self.win.orderOut_(None); self.win.close()
            except Exception:
                pass
            pop_regular()
        return self._result, vals

    def _reset(self):
        for spec, sld, fld in self._rows:
            d = spec[5]
            sld.setDoubleValue_(float(d)); fld.setStringValue_(_fmt(spec, d))

    def _save(self):
        self._result = "save"; NSApp.stopModal()

    def _cancel(self):
        self._result = "cancel"; NSApp.stopModal()
