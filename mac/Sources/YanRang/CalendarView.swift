import SwiftUI

/*
 * [INPUT]: 依赖 SwiftUI、Foundation.Calendar、Color 令牌、card() 修饰器
 * [OUTPUT]: 对外提供 CalendarView（月历选择器，带年/月下拉、记录红点）
 * [POS]: HistoryView 的左栏日历，1:1 复刻 desktop/src/components/ui/calendar.tsx 的视觉与交互
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

struct CalendarView: View {
    @Binding var selected: Date
    let logDays: Set<String>          // "yyyy-MM-dd"，有记录的日子 → 红点
    var cell: CGFloat = 42            // 放大格子（旧版太小）

    @State private var shown: Date = Date()   // 当前显示的月份（取该月任意一天）

    private var cal: Calendar { var c = Calendar(identifier: .gregorian); c.firstWeekday = 1; return c }
    private let weekdays = ["日", "一", "二", "三", "四", "五", "六"]
    private let years = Array(2015...(Calendar.current.component(.year, from: Date()) + 1))

    // 6×7 网格：含相邻月补位
    private var grid: [Date] {
        let comps = cal.dateComponents([.year, .month], from: shown)
        let first = cal.date(from: comps)!
        let lead = cal.component(.weekday, from: first) - cal.firstWeekday
        let startGap = (lead + 7) % 7
        let origin = cal.date(byAdding: .day, value: -startGap, to: first)!
        return (0..<42).map { cal.date(byAdding: .day, value: $0, to: origin)! }
    }

    private func setMonth(year: Int, month: Int) {
        if let d = cal.date(from: DateComponents(year: year, month: month, day: 1)) { shown = d }
    }

    var body: some View {
        VStack(spacing: 14) {
            // 年/月下拉（居中，captionLayout=dropdown 的等价物）
            HStack(spacing: 8) {
                Picker("", selection: Binding(
                    get: { cal.component(.month, from: shown) },
                    set: { setMonth(year: cal.component(.year, from: shown), month: $0) }
                )) {
                    ForEach(1...12, id: \.self) { Text("\($0) 月").tag($0) }
                }
                .labelsHidden().pickerStyle(.menu).fixedSize().clickable()

                Picker("", selection: Binding(
                    get: { min(years.last!, max(years.first!, cal.component(.year, from: shown))) },
                    set: { setMonth(year: $0, month: cal.component(.month, from: shown)) }
                )) {
                    ForEach(years, id: \.self) { Text(String($0)).tag($0) }
                }
                .labelsHidden().pickerStyle(.menu).fixedSize().clickable()
            }
            .frame(maxWidth: .infinity)

            // 星期表头
            HStack(spacing: 0) {
                ForEach(weekdays, id: \.self) { w in
                    Text(w).font(.system(size: 12)).foregroundStyle(Color.textTertiary)
                        .frame(width: cell, height: 26)
                }
            }

            // 日期网格
            VStack(spacing: 2) {
                ForEach(0..<6, id: \.self) { row in
                    HStack(spacing: 0) {
                        ForEach(0..<7, id: \.self) { col in
                            DayCell(date: grid[row * 7 + col])
                        }
                    }
                }
            }
        }
        .padding(14)
        .card(12)
        .onAppear { shown = selected }
        .onChange(of: selected) { _, new in shown = new }   // 外部改日期(如「今天」)时，月份跟着跳过去
    }

    @ViewBuilder
    private func DayCell(date: Date) -> some View {
        let inMonth = cal.isDate(date, equalTo: shown, toGranularity: .month)
        let isToday = cal.isDateInToday(date)
        let isSel = cal.isDate(date, inSameDayAs: selected)
        let hasLog = logDays.contains(ymdKey(date))

        Button {
            selected = date
            if !inMonth { shown = date }   // 点到相邻月 → 翻过去
        } label: {
            ZStack {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .fill(isSel ? Color.brand : .clear)
                Text("\(cal.component(.day, from: date))")
                    .font(.system(size: 14, weight: isToday || isSel ? .semibold : .regular))
                    .foregroundStyle(dayColor(inMonth: inMonth, isToday: isToday, isSel: isSel))
                // 有记录红点（选中时藏起，避免压在红底上）
                if hasLog && !isSel {
                    Circle().fill(Color.brand).frame(width: 4, height: 4)
                        .offset(y: cell / 2 - 7)
                }
            }
            .frame(width: cell, height: cell)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .clickable()
    }

    // 选中=白字（今天选中=黑字，红底上更醒目）；今天未选=红字；普通=主/次色
    private func dayColor(inMonth: Bool, isToday: Bool, isSel: Bool) -> Color {
        if isSel { return isToday ? .black : .white }
        if isToday { return .brand }
        return inMonth ? .appFg : Color.textTertiary.opacity(0.55)
    }
}
