import SwiftUI

/*
 * [INPUT]: 依赖 SwiftUI/AppKit、Color 令牌
 * [OUTPUT]: 对外提供 card()/clickable() 修饰器、BreathingDot、StatTile、ConfigRow
 * [POS]: mac/YanRang 复用组件层，承载 shadcn Card/状态点/统计块的原生等价物
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */
import AppKit

// 卡片底座：bg/surface(#fff) + border/default(#e5e5e5)，圆角 radius=10（Figma --radius）
extension View {
    func card(_ radius: CGFloat = 10) -> some View {
        background(RoundedRectangle(cornerRadius: radius, style: .continuous).fill(Color.card))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous).stroke(Color.hairline, lineWidth: 1))
    }

    // 可点提示:鼠标移上去变手型指针——所有可点元素统一加它,用户一看便知此处能点。
    // Tahoe(macOS 15+)用原生 pointerStyle(.link);旧系统降级 onHover+NSCursor。
    @ViewBuilder func clickable() -> some View {
        if #available(macOS 15.0, *) {
            self.pointerStyle(.link)
        } else {
            self.onHover { $0 ? NSCursor.pointingHand.push() : NSCursor.pop() }
        }
    }
}

// 呼吸灯：聆听=绿色脉冲 / 暂停=灰 / 准备=黄
struct BreathingDot: View {
    let active: Bool
    let muted: Bool
    @State private var pulse = false
    private var color: Color { active ? .ok : (muted ? Color.textTertiary : .warn) }

    var body: some View {
        ZStack {
            if active {
                Circle().fill(Color.ok).frame(width: 14, height: 14)
                    .scaleEffect(pulse ? 1.9 : 1).opacity(pulse ? 0 : 0.55)
            }
            Circle().fill(color).frame(width: 14, height: 14)
        }
        .frame(width: 14, height: 14)
        .onAppear { restart() }
        .onChange(of: active) { _, _ in restart() }   // 暂停/继续来回切换后，动画也能重启
    }

    private func restart() {
        pulse = false                                  // 先复位到起点(否则停留在透明放大态)
        guard active else { return }
        withAnimation(.easeOut(duration: 1.5).repeatForever(autoreverses: false)) { pulse = true }
    }
}

// 大数字统计块
struct StatTile: View {
    let value: String
    let label: String
    let accent: Bool
    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(value)
                .font(.system(size: 38, weight: .semibold))
                .monospacedDigit()
                .foregroundStyle(accent ? Color.brand : Color.appFg)
            Text(label).font(.system(size: 13)).foregroundStyle(Color.textTertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16)
        .card()
    }
}

// 配置项状态：配好=绿勾 / 未配=红叉
struct ConfigRow: View {
    let ok: Bool
    let label: String
    let detail: String
    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                .font(.system(size: 15))
                .foregroundStyle(ok ? Color.ok : Color.danger)
            Text(label).font(.system(size: 14, weight: .medium))
            Text(detail)
                .font(.system(size: 14))
                .foregroundStyle(ok ? Color.textSecondary : Color.danger)
                .lineLimit(1).truncationMode(.middle)
            Spacer(minLength: 0)
        }
    }
}
