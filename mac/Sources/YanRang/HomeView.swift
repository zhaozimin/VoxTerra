import SwiftUI

struct HomeView: View {
    @EnvironmentObject var engine: Engine

    var body: some View {
        VStack(spacing: 16) {
            // 状态英雄区
            HStack(spacing: 14) {
                BreathingDot(active: engine.listening, muted: engine.muted)
                VStack(alignment: .leading, spacing: 4) {
                    Text(engine.muted ? "已暂停" : engine.listening ? "正在聆听" : "准备中")
                        .font(.system(size: 27, weight: .bold))
                    Text(engine.muted ? "已暂停记录，点右侧按钮继续。" : "在后台把你说的话记成今天的笔记。")
                        .font(.system(size: 15)).foregroundStyle(Color.textSecondary)
                }
                Spacer()
                Button { engine.toggleMuted() } label: {
                    Label(engine.muted ? "继续录音" : "暂停录音",
                          systemImage: engine.muted ? "play.fill" : "pause.fill")
                        .padding(.horizontal, 2)
                }
                .controlSize(.large)
                .buttonStyle(.borderedProminent)
                .tint(engine.muted ? Color.brand : Color.sunken)
                .foregroundStyle(engine.muted ? .white : Color.appFg)
                .clickable()
            }
            .padding(18)
            .card()

            // 统计 + 基础配置状态
            HStack(spacing: 12) {
                // 两个统计块共占左半 → 配置卡占右半 = 1:1:2(对齐 Tauri flex-1/flex-1/flex-[2])
                HStack(spacing: 12) {
                    StatTile(value: "\(engine.count)", label: "今日已记", accent: true)
                    StatTile(value: "\(engine.dropped)", label: "今日滤除", accent: false)
                }
                .frame(maxWidth: .infinity)
                VStack(alignment: .leading, spacing: 9) {
                    ConfigRow(ok: engine.modelReady, label: "本地模型",
                              detail: engine.modelReady ? "已就绪 · \(engine.modelName)" : "未下载（必需）")
                    ConfigRow(ok: engine.enrolled, label: "声纹",
                              detail: engine.enrolled
                                ? (engine.speakerOn ? "已注册 · 声纹门开" : "已注册 · 声纹门关")
                                : "未注册（设置里可注册）")
                    ConfigRow(ok: !engine.vault.isEmpty, label: "保存位置",
                              detail: engine.vault.isEmpty ? "未设置" : engine.vault)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(16)
                .card()
            }
            .fixedSize(horizontal: false, vertical: true)

            // 今日实时流
            VStack(spacing: 0) {
                HStack {
                    Text("今天的记录").font(.system(size: 16, weight: .semibold))
                    Spacer()
                    Text("\(engine.today.count) 条").font(.system(size: 13)).foregroundStyle(Color.textSecondary)
                }
                .padding(.horizontal, 18).padding(.vertical, 12)
                Divider()
                ScrollView {
                    if engine.today.isEmpty {
                        Text("今天还没有记录。正常说话，文字会实时出现在这里。")
                            .font(.system(size: 15)).foregroundStyle(Color.textTertiary)
                            .frame(maxWidth: .infinity).padding(.vertical, 48)
                    } else {
                        LazyVStack(spacing: 0) {
                            // 倒序显示：最新说的排最顶(仅展示层翻转；Markdown 仍按时间正序 append)
                            ForEach(Array(engine.today.reversed())) { line in
                                HStack(alignment: .top, spacing: 12) {
                                    Text(line.time)
                                        .font(.system(size: 13, design: .monospaced))
                                        .foregroundStyle(Color.textTertiary)
                                        .frame(width: 46, alignment: .leading)
                                    Text(line.text).font(.system(size: 15)).textSelection(.enabled)
                                    Spacer(minLength: 0)
                                }
                                .padding(.horizontal, 18).padding(.vertical, 10)
                                Divider().opacity(0.35)
                            }
                        }
                    }
                }
            }
            .card()
            .frame(maxHeight: .infinity)
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.appBg)
    }
}

#Preview {
    @Previewable @StateObject var engine = Engine()
    HomeView()
        .environmentObject(engine)
        .frame(width: 1000, height: 700)
}
