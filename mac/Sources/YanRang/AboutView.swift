import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 Engine、Asset.logo、BrandIcon/Brand、Color 令牌、NSWorkspace
 * [OUTPUT]: 对外提供 AboutView（产品介绍 + 作者链接，真 logo + 真品牌图标）
 * [POS]: 关于页，1:1 复刻 desktop/src/pages/About.tsx
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

private func openURL(_ s: String) { if let u = URL(string: s) { NSWorkspace.shared.open(u) } }

private enum IconKind { case sf(String), brand(String) }

private struct LinkRow: View {
    let kind: IconKind
    let label: String
    let show: String
    let url: String
    @State private var hover = false

    var body: some View {
        Button { openURL(url) } label: {
            HStack(spacing: 12) {
                Group {
                    switch kind {
                    case .sf(let n): Image(systemName: n).font(.system(size: 15))
                    case .brand(let p): BrandIcon(path: p, color: hover ? .brand : .textTertiary)
                    }
                }
                .foregroundStyle(hover ? Color.brand : Color.textTertiary)
                .frame(width: 18, height: 18)

                Text(label).font(.system(size: 14, weight: .medium))
                Spacer()
                Text(show).font(.system(.caption, design: .monospaced)).foregroundStyle(Color.info)
            }
            .padding(.horizontal, 16).padding(.vertical, 12)
            .background(RoundedRectangle(cornerRadius: 10).fill(hover ? Color.sunken : Color.card))
            .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.hairline, lineWidth: 1))
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .clickable()
    }
}

struct AboutView: View {
    @EnvironmentObject var engine: Engine

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                // 头部：左 真 logo + 标题，右 版本 + 更新
                HStack(alignment: .center, spacing: 16) {
                    Image(nsImage: Asset.logo)
                        .resizable().interpolation(.high)
                        .frame(width: 64, height: 64)
                        .shadow(color: .black.opacity(0.12), radius: 3, y: 1)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("言壤").font(.system(size: 30, weight: .bold))
                        Text("本地实时语音日志 · VoiceLog").foregroundStyle(Color.textSecondary)
                    }
                    Spacer()
                    VStack(alignment: .trailing, spacing: 8) {
                        Label("v\(engine.version)", systemImage: "checkmark.seal.fill")
                            .font(.caption).fontWeight(.medium)
                            .padding(.horizontal, 8).padding(.vertical, 3)
                            .background(Capsule().fill((engine.updateLatest == nil ? Color.ok : Color.warn).opacity(0.15)))
                            .foregroundStyle(engine.updateLatest == nil ? Color.ok : Color.warn)
                        if let v = engine.updateLatest {
                            Button { openURL("https://github.com/zhaozimin/Recorder/releases/latest") } label: {
                                Label("更新到 v\(v)", systemImage: "arrow.triangle.2.circlepath")
                            }
                            .buttonStyle(.borderedProminent).tint(Color.brand).controlSize(.small).clickable()
                        } else {
                            Text("已是最新版本").font(.caption).foregroundStyle(Color.textTertiary)
                        }
                    }
                }

                // 介绍
                VStack(alignment: .leading, spacing: 7) {
                    Text("言壤 在你自己的电脑上实时聆听麦克风，把你说的话记成当天的文字笔记。")
                    Bullet("全程本地运行，不联网、不上传")
                    Bullet("音频转写后立即丢弃，绝不写盘")
                    Bullet("注册声纹后只记你本人，自动忽略外放视频与旁人")
                    Text("笔记按日期自动归档，随时可在「历史记录」里翻看。")
                }
                .font(.callout).foregroundStyle(Color.textSecondary).textSelection(.enabled)
                .padding(.top, 24)

                Divider().padding(.vertical, 22)

                // 作者
                Text("关于作者").font(.system(size: 14, weight: .semibold))
                (Text("作者 ") + Text("赵子民").fontWeight(.semibold).foregroundColor(Color.appFg)
                    + Text("（zhaozimin）。更多工具与资料见下方链接："))
                    .font(.callout).foregroundStyle(Color.textSecondary)
                    .padding(.top, 3).padding(.bottom, 12).textSelection(.enabled)

                VStack(spacing: 8) {
                    LinkRow(kind: .sf("globe"), label: "作者主页", show: "zhaozimin.cn", url: "https://zhaozimin.cn")
                    LinkRow(kind: .brand(Brand.obsidian), label: "Obsidian 资料库", show: "guangtou.me", url: "https://guangtou.me")
                    LinkRow(kind: .brand(Brand.github), label: "GitHub", show: "github.com/zhaozimin", url: "https://github.com/zhaozimin")
                    LinkRow(kind: .brand(Brand.x), label: "X", show: "@ZiminZhao", url: "https://x.com/ZiminZhao")
                }
            }
            .frame(maxWidth: 640, alignment: .leading)
            .padding(32)
            .frame(maxWidth: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.appBg)
    }
}

private func Bullet(_ s: String) -> some View {
    HStack(alignment: .firstTextBaseline, spacing: 8) {
        Circle().fill(Color.textTertiary).frame(width: 4, height: 4)
        Text(s)
    }
}

#Preview {
    @Previewable @StateObject var engine = Engine()
    AboutView()
        .environmentObject(engine)
        .frame(width: 1000, height: 700)
}
