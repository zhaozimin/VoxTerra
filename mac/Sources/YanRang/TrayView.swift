import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 Engine(@EnvironmentObject)、Environment(openWindow)、Startup(回前台形态)、NSWorkspace、Color 令牌
 * [OUTPUT]: 对外提供 TrayView(菜单栏弹窗:本地模型/声纹状态行 + 暂停 + 打开主窗口(回前台形态) + 作者三链接 + 退出)
 * [POS]: App.swift 的 MenuBarExtra(.window) 内容视图;与主窗口共享 engine,状态实时同步
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 *
 * 菜单栏托盘弹窗(MenuBarExtra .window)。原生可上色:🌐 主页(柔和红)/🪨 资料库(柔和紫)/🐱 GitHub(柔和蓝)。
 */
struct TrayView: View {
    @EnvironmentObject var engine: Engine
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Row(icon: engine.muted ? "play.fill" : "pause.fill",
                title: engine.muted ? "继续录音" : "暂停录音") { engine.toggleMuted() }
            Row(icon: "house", title: "打开主窗口") {
                Startup.enterForeground()       // 静默后台(无 Dock) → 恢复 Dock + 激活;非静默下幂等
                openWindow(id: "main")
            }

            Divider().padding(.vertical, 4)
            // 本地模型 / 声纹 是否启用——一眼可见(只读状态行，非按钮)
            StatusLine(ok: engine.modelReady, title: "本地模型",
                       detail: engine.modelReady ? engine.modelName : "未下载")
            StatusLine(ok: engine.enrolled, title: "声纹",
                       detail: engine.enrolled
                         ? (engine.speakerOn ? "已注册 · 门开" : "已注册 · 门关")
                         : "未注册")

            Divider().padding(.vertical, 4)
            Text("言壤 v\(engine.version)")
                .font(.caption).foregroundStyle(.tertiary)
                .padding(.horizontal, 10).padding(.vertical, 2)
            Divider().padding(.vertical, 4)

            Row(emoji: "🌐", title: "作者主页 · zhaozimin.cn", color: .softRed) { open("https://zhaozimin.cn") }
            Row(emoji: "🪨", title: "Obsidian 资料库 · guangtou.me", color: .softPurple) { open("https://guangtou.me") }
            Row(emoji: "🐱", title: "GitHub · zhaozimin", color: .softBlue) { open("https://github.com/zhaozimin") }

            Divider().padding(.vertical, 4)
            Row(icon: "power", title: "退出言壤") { NSApplication.shared.terminate(nil) }
        }
        .padding(8)
        .frame(width: 310)   // 加宽：Obsidian 资料库·guangtou.me 单行不折行
    }

    private func open(_ s: String) { if let u = URL(string: s) { NSWorkspace.shared.open(u) } }
}

#Preview {
    @Previewable @StateObject var engine = Engine()
    TrayView()
        .environmentObject(engine)
        .frame(width: 310, height: 280)
}

#Preview {
    TrayView()
        .environmentObject(Engine())
        .frame(width: 310, height: 280)
}

// 只读状态行：彩色指示 + 标题 + 详情(本地模型/声纹是否启用)
private struct StatusLine: View {
    let ok: Bool
    let title: String
    let detail: String
    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle.fill")
                .frame(width: 18).foregroundStyle(ok ? Color.ok : Color.warn)
            Text(title).font(.system(size: 13, weight: .medium))
            Spacer(minLength: 8)
            Text(detail).font(.system(size: 12)).foregroundStyle(.secondary)
                .lineLimit(1).truncationMode(.middle)
        }
        .padding(.horizontal, 8).padding(.vertical, 5)
    }
}

private struct Row: View {
    var icon: String? = nil
    var emoji: String? = nil
    let title: String
    var color: Color? = nil
    let action: () -> Void
    @State private var hover = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 9) {
                if let emoji { Text(emoji).frame(width: 18) }
                else if let icon { Image(systemName: icon).frame(width: 18).foregroundStyle(color ?? .primary) }
                Text(title).foregroundStyle(color ?? .primary).lineLimit(1).fixedSize()
                Spacer(minLength: 0)
            }
            .font(.system(size: 13, weight: .medium))
            .padding(.horizontal, 8).padding(.vertical, 6)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(RoundedRectangle(cornerRadius: 6, style: .continuous).fill(hover ? Color.primary.opacity(0.08) : .clear))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .clickable()
    }
}
