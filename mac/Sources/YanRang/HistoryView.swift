import SwiftUI

/*
 * [INPUT]: 依赖 Engine、CalendarView、card()、Color 令牌
 * [OUTPUT]: 对外提供 HistoryView（日历选日 + 全历史搜索）
 * [POS]: 历史页，1:1 复刻 desktop/src/pages/History.tsx（搜索置顶 + 左历右容）
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

private struct LineList: View {
    let lines: [LogLine]
    var body: some View {
        if lines.isEmpty {
            Text("这一天没有记录。")
                .font(.callout).foregroundStyle(Color.textTertiary)
                .frame(maxWidth: .infinity).padding(.vertical, 40)
        } else {
            ForEach(lines) { line in
                HStack(alignment: .top, spacing: 12) {
                    Text(line.time)
                        .font(.system(.caption, design: .monospaced)).monospacedDigit()
                        .foregroundStyle(Color.textTertiary).frame(width: 42, alignment: .leading)
                    Text(line.text).font(.callout).textSelection(.enabled)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 20).padding(.vertical, 10)
                Divider().opacity(0.4)
            }
        }
    }
}

struct HistoryView: View {
    @EnvironmentObject var engine: Engine
    @State private var date = Date()
    @State private var query = ""

    private var searching: Bool { !query.trimmingCharacters(in: .whitespaces).isEmpty }

    var body: some View {
        VStack(spacing: 16) {
            // 搜索：置顶通栏
            HStack(spacing: 8) {
                Image(systemName: "magnifyingglass").foregroundStyle(Color.textTertiary)
                TextField("搜索全部历史…", text: $query).textFieldStyle(.plain)
            }
            .padding(.horizontal, 12).frame(height: 36)
            .background(RoundedRectangle(cornerRadius: 8).fill(Color.card))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.hairline, lineWidth: 1))

            HStack(alignment: .top, spacing: 16) {
                // 左：放大的日历 + 今天
                VStack(spacing: 10) {
                    CalendarView(selected: $date, logDays: engine.historyDates())
                    Button { date = Date() } label: {
                        Text("今天").frame(maxWidth: .infinity)
                    }
                    .controlSize(.large).clickable()
                }
                .fixedSize(horizontal: true, vertical: false)

                // 右：当天记录 / 搜索结果
                VStack(spacing: 0) {
                    if searching {
                        let results = engine.search(query)
                        let total = results.reduce(0) { $0 + $1.lines.count }
                        HStack(spacing: 8) {
                            Image(systemName: "magnifyingglass").foregroundStyle(Color.textTertiary)
                            Text("找到 \(total) 行 · \(results.count) 天").font(.system(size: 14, weight: .semibold))
                            Spacer()
                        }
                        .padding(.horizontal, 20).padding(.vertical, 12)
                        Divider()
                        ScrollView {
                            LazyVStack(alignment: .leading, spacing: 0) {
                                if results.isEmpty {
                                    Text("没有匹配的记录。").font(.callout).foregroundStyle(Color.textTertiary)
                                        .frame(maxWidth: .infinity).padding(.vertical, 40)
                                } else {
                                    ForEach(results, id: \.date) { g in
                                        Text(g.date)
                                            .font(.caption).fontWeight(.medium).foregroundStyle(Color.textSecondary)
                                            .padding(.horizontal, 20).padding(.vertical, 6)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                            .background(Color.sunken)
                                        LineList(lines: g.lines)
                                    }
                                }
                            }
                        }
                    } else {
                        HStack {
                            Image(systemName: "calendar").foregroundStyle(Color.textTertiary)
                            Text(ymdKey(date)).font(.system(size: 14, weight: .semibold))
                            Spacer()
                            Text("\(engine.lines(for: date).count) 条")
                                .font(.caption).foregroundStyle(Color.textSecondary)
                                .padding(.horizontal, 8).padding(.vertical, 2)
                                .background(Capsule().fill(Color.sunken))
                        }
                        .padding(.horizontal, 20).padding(.vertical, 12)
                        Divider()
                        ScrollView { LazyVStack(alignment: .leading, spacing: 0) { LineList(lines: engine.lines(for: date)) } }
                    }
                }
                .card()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.appBg)
    }
}

#Preview {
    @Previewable @StateObject var engine = Engine()
    HistoryView()
        .environmentObject(engine)
        .frame(width: 1000, height: 700)
}
