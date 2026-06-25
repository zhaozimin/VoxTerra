import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 SwiftUI.Shape/Path、AppKit.NSImage、Bundle.main 的 Contents/Resources 资源
 * [OUTPUT]: 对外提供 SVGPath(Shape)、BrandIcon(View)、Brand 路径常量、Asset 资源加载器
 * [POS]: mac/YanRang 图标层，1:1 还原 desktop/src/components/ui/brand-icons.tsx 与 app-icon.png
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

// ============================================================================
//  SVG path → SwiftUI Path：支持 M m L l H h V v C c S s Q q A a Z z（品牌图标用不到 T/t，未实现）。
//  圆弧(A/a)用端点→圆心换算后采样折线逼近——图标尺度下视觉无损，免 bezier-arc 数学。
// ============================================================================
struct SVGPath: Shape {
    let d: String
    var viewBox: CGFloat = 24   // 正方形 viewBox 边长

    func path(in rect: CGRect) -> Path {
        let scale = min(rect.width, rect.height) / viewBox
        let ox = rect.minX + (rect.width  - viewBox * scale) / 2
        let oy = rect.minY + (rect.height - viewBox * scale) / 2
        func M(_ p: CGPoint) -> CGPoint { CGPoint(x: ox + p.x * scale, y: oy + p.y * scale) }

        var path = Path()
        var t = SVGTokenizer(d)
        var cur = CGPoint.zero, start = CGPoint.zero, ctrl: CGPoint? = nil
        var last: Character = " "

        while let raw = t.command() {
            let rel = raw.isLowercase
            let cmd = Character(raw.uppercased())
            switch cmd {
            case "M":
                var first = true
                while t.hasNumber {
                    let x = t.num(), y = t.num()
                    cur = rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y)
                    if first { path.move(to: M(cur)); start = cur; first = false }
                    else { path.addLine(to: M(cur)) }
                }
            case "L":
                while t.hasNumber {
                    let x = t.num(), y = t.num()
                    cur = rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y)
                    path.addLine(to: M(cur))
                }
            case "H":
                while t.hasNumber {
                    let x = t.num()
                    cur = rel ? CGPoint(x: cur.x + x, y: cur.y) : CGPoint(x: x, y: cur.y)
                    path.addLine(to: M(cur))
                }
            case "V":
                while t.hasNumber {
                    let y = t.num()
                    cur = rel ? CGPoint(x: cur.x, y: cur.y + y) : CGPoint(x: cur.x, y: y)
                    path.addLine(to: M(cur))
                }
            case "C":
                while t.hasNumber {
                    let x1 = t.num(), y1 = t.num(), x2 = t.num(), y2 = t.num(), x = t.num(), y = t.num()
                    let c1 = rel ? CGPoint(x: cur.x + x1, y: cur.y + y1) : CGPoint(x: x1, y: y1)
                    let c2 = rel ? CGPoint(x: cur.x + x2, y: cur.y + y2) : CGPoint(x: x2, y: y2)
                    let e  = rel ? CGPoint(x: cur.x + x,  y: cur.y + y)  : CGPoint(x: x, y: y)
                    path.addCurve(to: M(e), control1: M(c1), control2: M(c2))
                    ctrl = c2; cur = e
                }
            case "S":
                while t.hasNumber {
                    let x2 = t.num(), y2 = t.num(), x = t.num(), y = t.num()
                    let c1 = (last == "C" || last == "S"), reflect = ctrl ?? cur
                    let cp1 = c1 ? CGPoint(x: 2 * cur.x - reflect.x, y: 2 * cur.y - reflect.y) : cur
                    let c2  = rel ? CGPoint(x: cur.x + x2, y: cur.y + y2) : CGPoint(x: x2, y: y2)
                    let e   = rel ? CGPoint(x: cur.x + x,  y: cur.y + y)  : CGPoint(x: x, y: y)
                    path.addCurve(to: M(e), control1: M(cp1), control2: M(c2))
                    ctrl = c2; cur = e
                }
            case "Q":
                while t.hasNumber {
                    let x1 = t.num(), y1 = t.num(), x = t.num(), y = t.num()
                    let c = rel ? CGPoint(x: cur.x + x1, y: cur.y + y1) : CGPoint(x: x1, y: y1)
                    let e = rel ? CGPoint(x: cur.x + x,  y: cur.y + y)  : CGPoint(x: x, y: y)
                    path.addQuadCurve(to: M(e), control: M(c))
                    ctrl = c; cur = e
                }
            case "A":
                while t.hasNumber {
                    let rx = t.num(), ry = t.num(), rot = t.num()
                    let large = t.flag(), sweep = t.flag()
                    let x = t.num(), y = t.num()
                    let e = rel ? CGPoint(x: cur.x + x, y: cur.y + y) : CGPoint(x: x, y: y)
                    appendArc(&path, from: cur, to: e, rx: rx, ry: ry, rotDeg: rot, large: large, sweep: sweep, map: M)
                    cur = e
                }
            case "Z":
                path.closeSubpath(); cur = start
            default: break
            }
            last = cmd
        }
        return path
    }
}

/// SVG 椭圆弧 → 采样折线（W3C 端点→圆心换算）。
private func appendArc(_ path: inout Path, from: CGPoint, to: CGPoint,
                       rx rx0: CGFloat, ry ry0: CGFloat, rotDeg: CGFloat,
                       large: Bool, sweep: Bool, map: (CGPoint) -> CGPoint) {
    if from == to { return }
    if rx0 == 0 || ry0 == 0 { path.addLine(to: map(to)); return }
    var rx = abs(rx0), ry = abs(ry0)
    let phi = rotDeg * .pi / 180, cp = cos(phi), sp = sin(phi)
    let dx = (from.x - to.x) / 2, dy = (from.y - to.y) / 2
    let x1 =  cp * dx + sp * dy
    let y1 = -sp * dx + cp * dy
    let lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1 { let s = sqrt(lam); rx *= s; ry *= s }
    var num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    if num < 0 { num = 0 }
    let den = rx * rx * y1 * y1 + ry * ry * x1 * x1
    var co = den == 0 ? 0 : sqrt(num / den)
    if large == sweep { co = -co }
    let cxp =  co * rx * y1 / ry
    let cyp = -co * ry * x1 / rx
    let cx = cp * cxp - sp * cyp + (from.x + to.x) / 2
    let cy = sp * cxp + cp * cyp + (from.y + to.y) / 2
    func ang(_ ux: CGFloat, _ uy: CGFloat, _ vx: CGFloat, _ vy: CGFloat) -> CGFloat {
        let dot = ux * vx + uy * vy
        let len = sqrt((ux * ux + uy * uy) * (vx * vx + vy * vy))
        var a = acos(max(-1, min(1, len == 0 ? 1 : dot / len)))
        if ux * vy - uy * vx < 0 { a = -a }
        return a
    }
    let t1 = ang(1, 0, (x1 - cxp) / rx, (y1 - cyp) / ry)
    var dt = ang((x1 - cxp) / rx, (y1 - cyp) / ry, (-x1 - cxp) / rx, (-y1 - cyp) / ry)
    if !sweep && dt > 0 { dt -= 2 * .pi }
    if  sweep && dt < 0 { dt += 2 * .pi }
    let segs = max(2, Int(ceil(abs(dt) / (.pi / 16))))
    for k in 1...segs {
        let a = t1 + dt * CGFloat(k) / CGFloat(segs)
        let x = cp * rx * cos(a) - sp * ry * sin(a) + cx
        let y = sp * rx * cos(a) + cp * ry * sin(a) + cy
        path.addLine(to: map(CGPoint(x: x, y: y)))
    }
}

/// SVG 路径分词器：处理无分隔的 `-`/`.`、科学计数、紧贴的圆弧 flag。
private struct SVGTokenizer {
    private let s: [Character]
    private var i = 0
    init(_ str: String) { s = Array(str) }

    private func isSep(_ c: Character) -> Bool { c == " " || c == "," || c == "\n" || c == "\t" || c == "\r" }
    private mutating func skip() { while i < s.count, isSep(s[i]) { i += 1 } }

    mutating func command() -> Character? {
        skip()
        guard i < s.count, s[i].isLetter else { return nil }
        defer { i += 1 }; return s[i]
    }
    var hasNumber: Bool {
        var j = i
        while j < s.count, isSep(s[j]) { j += 1 }
        guard j < s.count else { return false }
        let c = s[j]; return c.isNumber || c == "-" || c == "+" || c == "."
    }
    mutating func num() -> CGFloat {
        skip()
        var str = ""
        if i < s.count, s[i] == "-" || s[i] == "+" { str.append(s[i]); i += 1 }
        while i < s.count, s[i].isNumber { str.append(s[i]); i += 1 }
        if i < s.count, s[i] == "." { str.append(s[i]); i += 1; while i < s.count, s[i].isNumber { str.append(s[i]); i += 1 } }
        if i < s.count, s[i] == "e" || s[i] == "E" {
            str.append(s[i]); i += 1
            if i < s.count, s[i] == "-" || s[i] == "+" { str.append(s[i]); i += 1 }
            while i < s.count, s[i].isNumber { str.append(s[i]); i += 1 }
        }
        return CGFloat(Double(str) ?? 0)
    }
    mutating func flag() -> Bool { skip(); guard i < s.count else { return false }; defer { i += 1 }; return s[i] == "1" }
}

// ============================================================================
//  品牌 logo（官方 simple-icons 路径，与 brand-icons.tsx 完全一致）
// ============================================================================
enum Brand {
    static let github = "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"
    static let obsidian = "M19.355 18.538a68.967 68.959 0 0 0 1.858-2.954.81.81 0 0 0-.062-.9c-.516-.685-1.504-2.075-2.042-3.362-.553-1.321-.636-3.375-.64-4.377a1.707 1.707 0 0 0-.358-1.05l-3.198-4.064a3.744 3.744 0 0 1-.076.543c-.106.503-.307 1.004-.536 1.5-.134.29-.29.6-.446.914l-.31.626c-.516 1.068-.997 2.227-1.132 3.59-.124 1.26.046 2.73.815 4.481.128.011.257.025.386.044a6.363 6.363 0 0 1 3.326 1.505c.916.79 1.744 1.922 2.415 3.5zM8.199 22.569c.073.012.146.02.22.02.78.024 2.095.092 3.16.29.87.16 2.593.64 4.01 1.055 1.083.316 2.198-.548 2.355-1.664.114-.814.33-1.735.725-2.58l-.01.005c-.67-1.87-1.522-3.078-2.416-3.849a5.295 5.295 0 0 0-2.778-1.257c-1.54-.216-2.952.19-3.84.45.532 2.218.368 4.829-1.425 7.531zM5.533 9.938c-.023.1-.056.197-.098.29L2.82 16.059a1.602 1.602 0 0 0 .313 1.772l4.116 4.24c2.103-3.101 1.796-6.02.836-8.3-.728-1.73-1.832-3.081-2.55-3.831zM9.32 14.01c.615-.183 1.606-.465 2.745-.534-.683-1.725-.848-3.233-.716-4.577.154-1.552.7-2.847 1.235-3.95.113-.235.223-.454.328-.664.149-.297.288-.577.419-.86.217-.47.379-.885.46-1.27.08-.38.08-.72-.014-1.043-.095-.325-.297-.675-.68-1.06a1.6 1.6 0 0 0-1.475.36l-4.95 4.452a1.602 1.602 0 0 0-.513.952l-.427 2.83c.672.59 2.328 2.316 3.335 4.711.09.21.175.43.253.653z"
    static let x = "M14.234 10.162 22.977 0h-2.072l-7.591 8.824L7.251 0H.258l9.168 13.343L.258 24H2.33l8.016-9.318L16.749 24h6.993zm-2.837 3.299-.929-1.329L3.076 1.56h3.182l5.965 8.532.929 1.329 7.754 11.09h-3.182z"
}

/// 品牌图标视图（用 even-odd 填充，保证 X 的内部镂空正确）。
struct BrandIcon: View {
    let path: String
    var color: Color = .textTertiary
    var body: some View {
        SVGPath(d: path).fill(color, style: FillStyle(eoFill: true))
    }
}

// ============================================================================
//  Bundle 资源：App logo（红底麦克风+无限）与菜单栏单色图标
// ============================================================================
enum Asset {
    /// 关于页/窗口用的彩色 App logo（红底 squircle）。
    static let logo: NSImage = NSImage.bundled("AppLogo") ?? NSImage()

    /// 菜单栏托盘摘要卡用的深色 App logo（=正在使用的 .icns 同源黑底 squircle，已裁成满铺）。
    static let logoDark: NSImage = NSImage.bundled("AppLogoDark") ?? logo

    /// 菜单栏模板图标（黑色描边，isTemplate=true 自动适配明暗与系统主题色）。
    static let trayIcon: NSImage = {
        let img = NSImage.bundled("TrayIcon")
            ?? NSImage(systemSymbolName: "infinity", accessibilityDescription: "言壤")!
        img.isTemplate = true
        img.size = NSSize(width: 24, height: 17)   // 放大更清晰，保持 166:120 比例（菜单栏上限内）
        return img
    }()
}

extension NSImage {
    /// 资源查找：唯一真相源 = Bundle.main(=Contents/Resources，由 bundle.sh/build-app.sh 平铺 PNG)。
    /// 绝不用 Bundle.module —— 其 SwiftPM 访问器在手工组装的 .app 里找不到资源包时会 fatalError 直接杀进程
    /// (而非返回 nil)，曾致分发版启动即崩。这里全程 Optional，缺失则由 Asset 降级到 SF Symbol。
    static func bundled(_ name: String) -> NSImage? {
        Bundle.main.url(forResource: name, withExtension: "png").flatMap(NSImage.init(contentsOf:))
    }
}
