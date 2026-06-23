import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 SwiftUI.Color / AppKit.NSColor
 * [OUTPUT]: 对外提供全套语义色令牌（随系统明暗自动切换，精确 Figma hex）
 * [POS]: mac/YanRang 设计层根基，1:1 复刻 desktop/src/index.css 的 :root / .dark 令牌
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

// ============================================================================
//  动态明暗色：用 NSColor 的 appearance 提供器，组件零判断、自动跟随系统。
// ============================================================================
extension NSColor {
    convenience init(hex: String) {
        let s = hex.trimmingCharacters(in: CharacterSet(charactersIn: "# "))
        var v: UInt64 = 0
        Scanner(string: s).scanHexInt64(&v)
        self.init(srgbRed: Double((v >> 16) & 0xFF) / 255,
                  green:   Double((v >> 8)  & 0xFF) / 255,
                  blue:    Double(v & 0xFF) / 255,
                  alpha: 1)
    }
}

extension Color {
    /// 明/暗双色（Figma hex）——自动响应 Light/Dark。
    init(light: String, dark: String) {
        self.init(nsColor: NSColor(name: nil) { ap in
            ap.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
                ? NSColor(hex: dark) : NSColor(hex: light)
        })
    }
    init(hex: String) { self.init(nsColor: NSColor(hex: hex)) }
}

// ============================================================================
//  语义令牌（与 index.css :root / .dark 逐项对齐）
// ============================================================================
extension Color {
    // —— surfaces ——
    static let appBg     = Color(light: "fafafa", dark: "0a0a0a")  // bg/page
    static let card      = Color(light: "ffffff", dark: "171717")  // bg/surface
    static let sunken    = Color(light: "f5f5f5", dark: "262626")  // bg/sunken (secondary/muted)
    // —— text ——
    static let appFg          = Color(light: "171717", dark: "fafafa")  // text/primary
    static let textSecondary  = Color(light: "525252", dark: "a3a3a3")
    static let textTertiary   = Color(light: "737373", dark: "737373")
    // —— border ——
    static let hairline       = Color(light: "e5e5e5", dark: "262626")  // border/default
    static let hairlineStrong = Color(light: "d4d4d4", dark: "404040")
    // —— brand（品牌红，暗色提亮一阶）——
    static let brand       = Color(light: "dc2626", dark: "ef4444")
    static let brandHover  = Color(light: "b91c1c", dark: "f87171")
    static let brandSubtle = Color(light: "fef2f2", dark: "1f1315")
    // —— feedback ——
    static let ok     = Color(light: "16a34a", dark: "22c55e")
    static let warn   = Color(light: "d97706", dark: "f59e0b")
    static let danger = Color(light: "dc2626", dark: "ef4444")
    static let info   = Color(light: "2563eb", dark: "3b82f6")
    // —— 托盘/关于链接：柔和红/紫/蓝（低饱和，明暗皆可读）——
    static let softRed    = Color(light: "d96c6c", dark: "e08a8a")
    static let softPurple = Color(light: "9e78d1", dark: "b79be0")
    static let softBlue   = Color(light: "6495db", dark: "85ade6")
}
