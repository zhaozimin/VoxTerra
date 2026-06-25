import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 Engine(@EnvironmentObject)、Environment(openWindow)、Startup(回前台形态)、NSWorkspace、Asset.logoDark(黑底 App 图标)、BrandIcon/Brand 矢量、Color 令牌(ok/warn/danger)
 * [OUTPUT]: 对外提供 TrayView(Quiet Dark 菜单栏弹窗:摘要卡(黑底 logo+言壤+版本号+录音中/已暂停+绿色录音开关) + 状态卡(本地模型/声纹 绿点) + 打开主窗口卡 + 链接卡(中性) + 退出红卡)
 * [POS]: App.swift 的 MenuBarExtra(.window) 内容视图;与主窗口共享 engine,状态实时同步;沿用系统弹窗作玻璃面板,内部 Quiet Dark 圆角卡分区
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 *
 * Quiet Dark 设计语言:前景色低透明叠层(卡填充 5% / 描边 6%)、三级文字(primary/secondary/tertiary)、
 * 单一绿强调(仅「录音中/已启用/在线」)、自绘绿轨道开关。系统 MenuBarExtra(.window) 即玻璃面板本体,
 * 故不再叠 .regularMaterial,只在其上铺圆角卡片——杜绝「面板套面板」双层边框。
 */
struct TrayView: View {
    @EnvironmentObject var engine: Engine
    @Environment(\.openWindow) private var openWindow

    // 链接卡的中性图标色：单绿铁律下,品牌图标一律前景中性,不抢「绿=正向」的唯一性
    private let iconTint = Color.primary.opacity(0.85)

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            summaryCard          // App 图标 + 言壤 + 录音中/已暂停 + 绿色录音开关
            statusCard           // 本地模型 / 声纹：绿点(在线) / 橙点(缺失)
            OpenMainCard {       // 打开主窗口(经 Startup 回前台形态)
                Startup.enterForeground()
                openWindow(id: "main")
            }
            linksCard            // 作者三链接：中性矢量图标 + 外链箭头
            QuitCard()           // 退出言壤：红 power、居中
        }
        .padding(10)
        .frame(width: 312)
    }

    // MARK: - 摘要卡：身份 + 录音开关

    private var summaryCard: some View {
        HStack(spacing: 12) {
            Image(nsImage: Asset.logoDark)
                .resizable()
                .interpolation(.high)
                .aspectRatio(contentMode: .fit)
                .frame(width: 34, height: 34)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))

            VStack(alignment: .leading, spacing: 2) {
                // 品牌名 + 版本号同行(版本号小一号、次级色,紧随其后)
                (Text("言壤").font(.system(size: 14, weight: .semibold))
                    + Text("  v\(engine.version)")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.secondary))
                    .lineLimit(1)
                Text(engine.muted ? "已暂停" : "录音中")
                    .font(.system(size: 11))
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 8)

            // 录音中 = 开关打开 = 绿轨道；暂停 = 关 = 灰轨道。点击即 toggleMuted。
            QuietSwitch(isOn: Binding(get: { !engine.muted }, set: { _ in engine.toggleMuted() }))
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .quietCard()
    }

    // MARK: - 状态卡：本地模型 / 声纹 是否就绪(只读)

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 11) {
            statusRow(ok: engine.modelReady, title: "本地模型",
                      detail: engine.modelReady ? engine.modelName : "未下载")
            statusRow(ok: engine.enrolled, title: "声纹",
                      detail: engine.enrolled
                        ? (engine.speakerOn ? "已注册 · 门开" : "已注册 · 门关")
                        : "未注册")
        }
        .padding(12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .quietCard()
    }

    private func statusRow(ok: Bool, title: String, detail: String) -> some View {
        HStack(spacing: 10) {
            Circle()
                .fill(ok ? Color.ok : Color.warn)
                .frame(width: 7, height: 7)
            Text(title).font(.system(size: 13, weight: .medium))
            Spacer(minLength: 8)
            Text(detail)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
        }
    }

    // MARK: - 链接卡：作者三链接(中性)

    private var linksCard: some View {
        VStack(spacing: 2) {
            LinkRow(name: "作者主页", domain: "zhaozimin.cn", url: "https://zhaozimin.cn") {
                Image(systemName: "globe")
                    .font(.system(size: 14))
                    .foregroundStyle(iconTint)
            }
            LinkRow(name: "Obsidian 资料库", domain: "guangtou.me", url: "https://guangtou.me") {
                BrandIcon(path: Brand.obsidian, color: iconTint).frame(width: 15, height: 15)
            }
            LinkRow(name: "GitHub", domain: "zhaozimin", url: "https://github.com/zhaozimin") {
                BrandIcon(path: Brand.github, color: iconTint).frame(width: 15, height: 15)
            }
        }
        .padding(6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .quietCard()
    }
}

// ============================================================================
// MARK: - QuietSwitch  自绘开关(开→绿轨道、关→灰轨道,白滑块弹簧滑动)
// ----------------------------------------------------------------------------
// 轨道底色随 isOn 渐变 = 状态的明确反馈;前景 20% 灰为「关」,Color.ok 绿为「开」。
// 替代 .tint 在 macOS 上不可靠的原生 Toggle。
// ============================================================================
private struct QuietSwitch: View {
    @Binding var isOn: Bool
    var onColor: Color = .ok

    private let trackW: CGFloat = 38
    private let trackH: CGFloat = 22
    private let knob: CGFloat = 18
    private let inset: CGFloat = 2
    private var travel: CGFloat { trackW - knob - inset * 2 }

    var body: some View {
        ZStack(alignment: .leading) {
            Capsule().fill(isOn ? onColor : Color.primary.opacity(0.20))
            Circle()
                .fill(.white)
                .frame(width: knob, height: knob)
                .shadow(color: .black.opacity(0.25), radius: 1, x: 0, y: 0.5)
                .padding(inset)
                .offset(x: isOn ? travel : 0)
        }
        .frame(width: trackW, height: trackH)
        .animation(.spring(response: 0.25, dampingFraction: 0.85), value: isOn)
        .contentShape(Capsule())
        .onTapGesture { isOn.toggle() }
        .clickable()
        .accessibilityElement()
        .accessibilityAddTraits(.isButton)
        .accessibilityValue(Text(isOn ? "On" : "Off"))
    }
}

// ============================================================================
// MARK: - 整卡可点的动作卡(打开主窗口 / 退出)：hover 提亮卡底
// ============================================================================

/// 打开主窗口：房子图标 + 标题 + 右尖角,整卡可点。
private struct OpenMainCard: View {
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: "house")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(.secondary)
                    .frame(width: 18)
                Text("打开主窗口").font(.system(size: 13, weight: .medium))
                Spacer(minLength: 0)
                Image(systemName: "chevron.right")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 11)
            .frame(maxWidth: .infinity, alignment: .leading)
            .actionCardBackground(hover: hover, radius: 12)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .clickable()
    }
}

/// 退出言壤：红 power + 标题,居中,整卡可点。
private struct QuitCard: View {
    @State private var hover = false

    var body: some View {
        Button { NSApplication.shared.terminate(nil) } label: {
            HStack(spacing: 8) {
                Spacer(minLength: 0)
                Image(systemName: "power")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color.danger)
                Text("退出言壤")
                    .font(.system(size: 13))
                    .foregroundStyle(.primary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity)
            .actionCardBackground(hover: hover, radius: 10)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .clickable()
    }
}

// ============================================================================
// MARK: - 链接行：中性图标 + 名称(primary) + 域名(tertiary) + 外链箭头
// ============================================================================
private struct LinkRow<Icon: View>: View {
    let name: String
    let domain: String
    let url: String
    @ViewBuilder var icon: () -> Icon
    @State private var hover = false

    var body: some View {
        Button { openExternal(url) } label: {
            HStack(spacing: 10) {
                icon().frame(width: 18, height: 18)
                (Text(name).foregroundStyle(.primary)
                    + Text(" · \(domain)").foregroundStyle(.tertiary))
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
                Spacer(minLength: 6)
                Image(systemName: "arrow.up.forward")
                    .font(.system(size: 10, weight: .semibold))
                    .foregroundStyle(.tertiary)
            }
            .padding(.horizontal, 8)
            .padding(.vertical, 7)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(hover ? Color.primary.opacity(0.06) : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .clickable()
    }
}

// ============================================================================
// MARK: - Quiet Dark 卡片底座（前景色低透明叠层，禁用固定灰阶）
// ============================================================================
private extension View {
    /// 静态卡片：前景 5% 填充 + 6% 描边。
    func quietCard(_ radius: CGFloat = 12) -> some View {
        background(RoundedRectangle(cornerRadius: radius, style: .continuous)
            .fill(Color.primary.opacity(0.05)))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1))
    }

    /// 动作卡背景：hover 时填充 5%→7% 微提亮。
    func actionCardBackground(hover: Bool, radius: CGFloat) -> some View {
        background(RoundedRectangle(cornerRadius: radius, style: .continuous)
            .fill(Color.primary.opacity(hover ? 0.07 : 0.05)))
            .overlay(RoundedRectangle(cornerRadius: radius, style: .continuous)
                .strokeBorder(Color.primary.opacity(0.06), lineWidth: 1))
    }
}

private func openExternal(_ s: String) {
    if let u = URL(string: s) { NSWorkspace.shared.open(u) }
}

#Preview {
    @Previewable @StateObject var engine = Engine()
    TrayView()
        .environmentObject(engine)
        .frame(width: 332, height: 420)
}

#Preview {
    TrayView()
        .environmentObject(Engine())
        .frame(width: 332, height: 420)
}
