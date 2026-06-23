import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 Engine、card()、Color 令牌
 * [OUTPUT]: 对外提供 SettingsView（标签页式设置：语言时区/模型下载/保存位置/关键词/参数/配置）
 * [POS]: 设置页，1:1 复刻 desktop/src/pages/Settings.tsx（页内胶囊标签 + 内容区）；模型下载页驱动 Engine.models
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

// ============================================================================
//  参数定义（与 Python 引擎 settings_ui.PARAMS 一致）
// ============================================================================
struct Param: Identifiable {
    var id: String { name }
    let name: String
    let key: String            // 对应 config.yaml 键(下发 set_params / 从回显取值)
    let min: Double, max: Double, step: Double, def: Double
    let isInt: Bool
    let lo: String, hi: String
}

let PARAMS: [Param] = [
    .init(name: "切句灵敏度", key: "vad_threshold", min: 0.30, max: 0.90, step: 0.05, def: 0.60, isInt: false, lo: "越小越易开句（噪声易误触）", hi: "越大越严（轻声可能漏）"),
    .init(name: "最短句长 (ms)", key: "min_speech_ms", min: 100, max: 1000, step: 50, def: 300, isInt: true, lo: "越小短噪声易进", hi: "越大短句被丢"),
    .init(name: "停顿断句 (ms)", key: "min_silence_ms", min: 300, max: 1500, step: 50, def: 700, isInt: true, lo: "越小切得碎", hi: "越大合成长句"),
    .init(name: "近场响度门 (dBFS)", key: "min_rms_dbfs", min: -60, max: -30, step: 1, def: -45, isInt: false, lo: "越小（更负）收得越远", hi: "越大只收很近"),
    .init(name: "声纹严格度", key: "speaker_threshold", min: 0.10, max: 0.80, step: 0.01, def: 0.35, isInt: false, lo: "越小越宽松（可能混入他人）", hi: "越大越严（可能误丢你）"),
    .init(name: "短句豁免 (s)", key: "speaker_min_verify_sec", min: 0, max: 3, step: 0.1, def: 1.2, isInt: false, lo: "越小更多短句也验", hi: "越大更多短句放行"),
    .init(name: "单句上限 (s)", key: "max_utterance_sec", min: 10, max: 60, step: 5, def: 30, isInt: true, lo: "越小切得勤", hi: "越大允许长段"),
]

// ============================================================================
//  页内标签
// ============================================================================
enum SettingsTab: CaseIterable, Identifiable {
    case lang, models, path, keywords, params, config
    var id: Self { self }
    var title: String {
        switch self {
        case .lang: "语言和时区"; case .models: "模型下载"; case .path: "保存位置"; case .keywords: "关键词"
        case .params: "参数设置"; case .config: "配置文件"
        }
    }
    var icon: String {
        switch self {
        case .lang: "globe"; case .models: "arrow.down.circle"; case .path: "folder"; case .keywords: "tag"
        case .params: "slider.horizontal.3"; case .config: "doc.text"
        }
    }
}

struct SettingsView: View {
    @State private var tab: SettingsTab = .lang   // 默认打开「语言和时区」

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            TabsList(tab: $tab)                 // 胶囊标签（左对齐，w-fit）
            Group {
                switch tab {
                case .lang: LangTab()
                case .models: ModelsTab()
                case .path: PathTab()
                case .keywords: KeywordsTab()
                case .params: ParamsTab()
                case .config: ConfigTab()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(Color.appBg)
    }
}

// 胶囊标签条：bg/sunken 容器 + 选中 bg/surface + 阴影（shadcn TabsList）
private struct TabsList: View {
    @Binding var tab: SettingsTab
    var body: some View {
        HStack(spacing: 2) {
            ForEach(SettingsTab.allCases) { t in TabItem(t: t, tab: $tab) }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 9).fill(Color.sunken))
    }
}

private struct TabItem: View {
    let t: SettingsTab
    @Binding var tab: SettingsTab
    @State private var hover = false
    private var active: Bool { tab == t }
    var body: some View {
        Button { tab = t } label: {
            HStack(spacing: 6) {
                Image(systemName: t.icon).font(.system(size: 13))
                Text(t.title).font(.system(size: 13, weight: .medium))
            }
            .padding(.horizontal, 12).padding(.vertical, 5)
            .foregroundStyle(active ? Color.appFg : (hover ? Color.appFg : Color.textTertiary))
            .background(
                // 选中=实心卡片+阴影;未选中悬停=半透明卡底,明确"可点"提示(就像导航标签)
                RoundedRectangle(cornerRadius: 6)
                    .fill(active ? Color.card : (hover ? Color.card.opacity(0.55) : .clear))
                    .shadow(color: active ? .black.opacity(0.12) : .clear, radius: 1, y: 1)
            )
            .contentShape(Rectangle())
            .animation(.easeOut(duration: 0.12), value: hover)
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .clickable()
    }
}

// ---------------------------------------------------------------- 语言和时区
// 直接绑定 engine 的回显字段(来自 config.yaml):选择即下命令保存、引擎写回、下拉显已存值。
// 选项值用 config 的真实取值("" = 跟随系统/无;时区用 IANA),与引擎零映射歧义。
private struct LangTab: View {
    @EnvironmentObject var engine: Engine
    private let langOpts: [(String, String)] = [("", "跟随系统"), ("zh", "简体中文"), ("en", "English"), ("ja", "日本語")]
    private let secOpts:  [(String, String)] = [("", "无"), ("zh", "简体中文"), ("en", "English"), ("ja", "日本語")]
    private let tzOpts:   [(String, String)] = [("", "跟随系统"), ("Asia/Shanghai", "Asia/Shanghai"), ("Asia/Tokyo", "Asia/Tokyo"), ("America/New_York", "America/New_York")]

    var body: some View {
        VStack(spacing: 0) {
            LangRow(label: "界面语言", hint: "菜单与窗口显示的语言",
                    sel: Binding(get: { engine.cfgUILang }, set: { engine.setUILang($0) }), opts: langOpts)
            Divider()
            LangRow(label: "主语言（转写语言）", hint: "你日常主要说的话，决定 Whisper 按什么语言识别",
                    sel: Binding(get: { engine.cfgPrimaryLang }, set: { engine.setPrimaryLang($0) }), opts: langOpts)
            Divider()
            LangRow(label: "辅语言（夹杂语言）", hint: "日常夹杂的外语，用来强化识别提示",
                    sel: Binding(get: { engine.cfgSecondaryLang }, set: { engine.setSecondaryLang($0) }), opts: secOpts)
            Divider()
            LangRow(label: "时区", hint: "时间戳与当天归属日；留空跟随系统本地",
                    sel: Binding(get: { engine.cfgTimezone }, set: { engine.setTimezone($0) }), opts: tzOpts)
        }
        .padding(.horizontal, 18)
        .card()
    }
}

private struct LangRow: View {
    let label: String, hint: String
    @Binding var sel: String
    let opts: [(String, String)]
    // 当前选中项的显示文案
    private var current: String { opts.first { $0.0 == sel }?.1 ?? "" }

    var body: some View {
        HStack(spacing: 16) {
            VStack(alignment: .leading, spacing: 2) {
                Text(label).font(.system(size: 14, weight: .medium))
                Text(hint).font(.caption).foregroundStyle(Color.textTertiary)
            }
            Spacer()
            // 固定宽度自定义下拉：1:1 复刻 Tauri 的 w-48 h-9 select。
            // 原生 .menu Picker 会按内容自适应、忽略 .frame 宽度 → 四个下拉宽度不一；
            // 改用固定 192×36 容器承载选中文案 + chevron，宽度恒定一致。
            Menu {
                ForEach(opts, id: \.0) { opt in
                    Button(opt.1) { sel = opt.0 }
                }
            } label: {
                HStack(spacing: 8) {
                    Text(current).font(.system(size: 13)).foregroundStyle(Color.appFg)
                        .lineLimit(1).truncationMode(.tail)
                    Spacer(minLength: 8)                       // 撑开 → chevron 钉死最右缘
                    Image(systemName: "chevron.up.chevron.down")
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(Color.textTertiary)
                }
                // HStack 显式定宽(168 + 左右各 12 = 192)：Spacer 真正撑开 → chevron 贴右、四个下拉对齐成一条竖线。
                .frame(width: 168, height: 36)
                .padding(.horizontal, 12)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color.card))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.hairline, lineWidth: 1))
                .contentShape(Rectangle())
            }
            // .button 样式 + .plain 按钮 + .menuIndicator(.hidden)：去系统边框、去系统指示符，
            // 只渲染自定义 label（borderlessButton 会强塞自己的 ⇕ 到左侧，menuIndicator 还压不掉它）。
            .menuStyle(.button)
            .buttonStyle(.plain)
            .menuIndicator(.hidden)
            .fixedSize()
            .clickable()
        }
        .padding(.vertical, 14)
    }
}

// ---------------------------------------------------------------- 模型下载
private struct ModelsTab: View {
    @EnvironmentObject var engine: Engine
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // 说明卡
            VStack(alignment: .leading, spacing: 4) {
                Text("本地语音模型").font(.system(size: 14, weight: .medium))
                Text("模型全部在本机运行，语音不出本地。从项目 GitHub Release 直链下载（国内可达、支持断点续传）。体积越大越准、越吃内存——先下「Turbo」即可。")
                    .font(.caption).foregroundStyle(Color.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16).card()

            // 下载中断/取消的反馈：明确告知"进度已保留、可续传"，别让用户以为白下
            if let note = engine.modelNote {
                HStack(spacing: 8) {
                    Image(systemName: "arrow.clockwise.circle")
                    Text(note).fixedSize(horizontal: false, vertical: true)
                }
                .font(.caption).foregroundStyle(Color.textSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 14).padding(.vertical, 10)
                .background(Color.brandSubtle, in: RoundedRectangle(cornerRadius: 8))
            }

            // 模型列表（单卡分隔行）
            ScrollView {
                VStack(spacing: 0) {
                    ForEach(Array(engine.models.enumerated()), id: \.element.id) { i, m in
                        if i > 0 { Divider() }
                        ModelRow(model: m)
                    }
                }
                .padding(.horizontal, 16)
                .card()
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    }
}

private struct ModelRow: View {
    @EnvironmentObject var engine: Engine
    let model: ModelItem
    private var isActive: Bool { model.filename == engine.modelName && model.state == .downloaded }

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 6) {
                    Text(model.name).font(.system(size: 14, weight: .medium))
                    if model.recommended { Badge(text: "推荐", fg: Color.brand, bg: Color.brandSubtle) }
                    if isActive { Badge(text: "使用中", fg: Color.ok, bg: Color.ok.opacity(0.15)) }
                }
                Text(model.desc).font(.caption).foregroundStyle(Color.textTertiary)
            }
            Spacer()
            Text(model.sizeText).font(.system(.caption, design: .monospaced))
                .foregroundStyle(Color.textTertiary).monospacedDigit()
                .frame(width: 70, alignment: .trailing)
            stateControl.frame(width: 168, alignment: .trailing)
        }
        .padding(.vertical, 14)
    }

    @ViewBuilder private var stateControl: some View {
        switch model.state {
        case .notDownloaded:
            Button { engine.downloadModel(model.id) } label: {
                Label("下载", systemImage: "arrow.down.circle")
            }
            .buttonStyle(.borderedProminent).tint(Color.brand).clickable()
        case .downloading(let p):
            HStack(spacing: 8) {
                ProgressView(value: p).frame(width: 66)
                Text("\(Int(p * 100))%").font(.system(.caption, design: .monospaced))
                    .monospacedDigit().foregroundStyle(Color.textSecondary)
                // 取消:停下载;已下部分(.part)保留,下次点「下载」自动续传
                Button { engine.cancelModel(model.id) } label: {
                    Image(systemName: "xmark.circle.fill")
                }
                .buttonStyle(.plain).foregroundStyle(Color.textTertiary).clickable()
                .help("停止下载（已下部分保留，下次续传）")
            }
        case .downloaded:
            if isActive {
                Label("已就绪", systemImage: "checkmark.circle.fill")
                    .font(.caption).foregroundStyle(Color.ok)
            } else {
                // 已下载但非当前：可一键切换为当前模型 + 删除（图标，省横向空间）
                HStack(spacing: 8) {
                    Button { engine.useModel(model.id) } label: {
                        Label("使用", systemImage: "checkmark.circle")
                    }
                    .buttonStyle(.bordered).tint(Color.brand).clickable()
                    Button(role: .destructive) { engine.deleteModel(model.id) } label: {
                        Image(systemName: "trash")
                    }
                    .buttonStyle(.bordered).clickable()
                    .help("删除此模型")
                }
            }
        }
    }
}

// 小徽标（推荐/使用中）
private struct Badge: View {
    let text: String, fg: Color, bg: Color
    var body: some View {
        Text(text).font(.system(size: 10, weight: .semibold))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(Capsule().fill(bg)).foregroundStyle(fg)
    }
}

// ---------------------------------------------------------------- 保存位置
private struct PathTab: View {
    @EnvironmentObject var engine: Engine
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("语音日志保存位置").font(.system(size: 14, weight: .medium))
            HStack(spacing: 12) {
                Text(engine.vault)
                    .font(.system(.callout, design: .monospaced))
                    .lineLimit(1).truncationMode(.middle)
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(RoundedRectangle(cornerRadius: 6).fill(Color.sunken))
                Button("更改…") {
                    let panel = NSOpenPanel()
                    panel.canChooseDirectories = true
                    panel.canChooseFiles = false
                    panel.allowsMultipleSelection = false
                    panel.prompt = "选择"
                    if panel.runModal() == .OK, let url = panel.url {
                        engine.setVault(url.path)        // 下命令，由引擎写 config.vault_path
                    }
                }
                .clickable()
            }
            Text("笔记按日期写成 Markdown；外置盘掉线会自动回退内置备用盘，绝不丢字。")
                .font(.caption).foregroundStyle(Color.textTertiary)
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

// ---------------------------------------------------------------- 关键词
private struct KeywordsTab: View {
    @EnvironmentObject var engine: Engine
    @State private var text = ""
    @State private var saved = false
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("每行一条：写「错词 = 正词」做精确纠错；只写一个词进识别词库。保存即生效。")
                .font(.caption).foregroundStyle(Color.textTertiary)
            TextEditor(text: $text)
                .font(.system(.callout, design: .monospaced))
                .scrollContentBackground(.hidden)
                .padding(8)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(RoundedRectangle(cornerRadius: 6).fill(Color.sunken))
            HStack {
                if saved { Label("已保存，即时生效", systemImage: "checkmark").font(.caption).foregroundStyle(Color.ok) }
                Spacer()
                Button("保存关键词") { engine.saveKeywords(text); saved = true }.keyboardShortcut(.defaultAction).clickable()
            }
        }
        .padding(20)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .card()
        .onAppear { text = engine.cfgKeywords }                 // 回显已存关键词
        .onChange(of: text) { _, _ in saved = false }
    }
}

// ---------------------------------------------------------------- 参数设置
private struct ParamsTab: View {
    @EnvironmentObject var engine: Engine
    @State private var vals: [String: Double] = Dictionary(uniqueKeysWithValues: PARAMS.map { ($0.name, $0.def) })
    @State private var saved = false

    private let cols = [GridItem(.flexible(), spacing: 12), GridItem(.flexible(), spacing: 12)]

    var body: some View {
        VStack(spacing: 12) {
            ScrollView {
                LazyVGrid(columns: cols, spacing: 12) {
                    // 声纹注册（与参数卡同尺寸，作为首格）
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text("声纹注册").font(.system(size: 14, weight: .medium))
                            Spacer()
                            HStack(spacing: 4) {
                                Image(systemName: "checkmark.shield.fill").font(.system(size: 12))
                                Text(engine.enrolled ? "已注册" : "未注册").font(.caption)
                            }
                            .foregroundStyle(engine.enrolled ? Color.ok : Color.danger)
                        }
                        HStack {
                            HStack(spacing: 8) {
                                Text("声纹门").font(.caption).foregroundStyle(Color.textSecondary)
                                // 自定义 Binding：翻转即下命令(乐观更新在 Engine 内)，避免被每拍 reloadState 反向触发
                                Toggle("", isOn: Binding(
                                    get: { engine.speakerOn },
                                    set: { engine.setSpeakerGate($0) }
                                )).toggleStyle(.switch).labelsHidden()
                                    .disabled(!engine.enrolled).clickable()
                            }
                            Spacer()
                            Button { engine.requestEnroll() } label: {   // 先弹确认须知,确定后再进朗读窗
                                Label(engine.enrolled ? "重新注册" : "注册声音", systemImage: "mic")
                            }
                            .buttonStyle(.bordered).clickable()
                        }
                    }
                    .padding(16).card()

                    ForEach(PARAMS) { p in
                        ParamCard(p: p, value: Binding(
                            get: { vals[p.name] ?? p.def },
                            set: { vals[p.name] = $0; saved = false }
                        ))
                    }
                }
                .padding(.bottom, 4)
            }
            Divider()
            HStack(spacing: 12) {
                Spacer()
                if saved {
                    Label("已保存，即时生效", systemImage: "checkmark")
                        .font(.caption).foregroundStyle(Color.ok)
                }
                Button {
                    for p in PARAMS { vals[p.name] = p.def }
                    engine.saveParams(paramPayload()); saved = true
                } label: {
                    Label("恢复默认", systemImage: "arrow.counterclockwise")
                }
                .buttonStyle(.borderless).clickable()
                Button("保存设置") { engine.saveParams(paramPayload()); saved = true }.keyboardShortcut(.defaultAction).clickable()
            }
        }
        .onAppear { for p in PARAMS { if let v = engine.cfgParams[p.key] { vals[p.name] = v } } }   // 回显已存参数
    }

    // 把当前滑块值按 config 键打包(下发 set_params)
    private func paramPayload() -> [String: Double] {
        Dictionary(uniqueKeysWithValues: PARAMS.map { ($0.key, vals[$0.name] ?? $0.def) })
    }
}

private struct ParamCard: View {
    let p: Param
    @Binding var value: Double
    private var fmt: String {
        p.isInt ? String(Int(value.rounded())) : String(format: p.step < 0.05 ? "%.2f" : "%.1f", value)
    }
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(p.name).font(.system(size: 14, weight: .medium))
                Spacer()
                Text(fmt).font(.system(.callout, design: .monospaced))
                    .foregroundStyle(Color.textSecondary).monospacedDigit()
            }
            ParamSlider(value: $value, range: p.min...p.max, step: p.step, def: p.def)
            HStack {
                Text("← \(p.lo)")
                Spacer()
                Text("\(p.hi) →")
            }
            .font(.caption).foregroundStyle(Color.textTertiary)
        }
        .padding(16).card()
    }
}

// 参数滑块：默认值=原点(中心刻度)，填充从原点向左/右延伸，直观展示偏移方向。
// 细轨 + 小圆钮，复刻 shadcn Slider 观感。
private struct ParamSlider: View {
    @Binding var value: Double
    let range: ClosedRange<Double>
    let step: Double
    let def: Double

    private let thumb: CGFloat = 16

    var body: some View {
        GeometryReader { geo in
            let w = geo.size.width
            let r = thumb / 2
            let usable = max(1, w - thumb)
            let lo = range.lowerBound
            let span = range.upperBound - lo
            let curX = r + CGFloat((value - lo) / span) * usable
            let defX = r + CGFloat((def - lo) / span) * usable

            ZStack(alignment: .leading) {
                Capsule().fill(Color.sunken).frame(height: 5)                 // 轨道
                Capsule().fill(Color.brand)                                   // 偏移填充(原点→当前)
                    .frame(width: abs(curX - defX), height: 5)
                    .offset(x: min(curX, defX))
                Capsule().fill(Color.hairlineStrong).frame(width: 2, height: 11)   // 原点刻度=默认值
                    .offset(x: defX - 1)
                Circle().fill(.white).frame(width: thumb, height: thumb)      // 圆钮
                    .overlay(Circle().stroke(Color.hairlineStrong, lineWidth: 1))
                    .shadow(color: .black.opacity(0.18), radius: 1.5, y: 1)
                    .offset(x: curX - r)
            }
            .frame(height: thumb)
            .contentShape(Rectangle())
            .gesture(DragGesture(minimumDistance: 0).onChanged { g in
                let frac = max(0, min(1, (g.location.x - r) / usable))
                let raw = lo + Double(frac) * span
                let snapped = (raw / step).rounded() * step
                value = min(range.upperBound, max(lo, snapped))
            })
        }
        .frame(minWidth: 120, minHeight: thumb, maxHeight: thumb)   // 防极窄容器下圆钮/刻度溢出轨道
    }
}

// ---------------------------------------------------------------- 配置文件
private struct ConfigTab: View {
    @EnvironmentObject var engine: Engine
    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("高级配置文件（config.yaml）").font(.system(size: 14, weight: .medium))
            Text("这里是全部设置的底层文件，含术语偏置、回退目录等界面之外的项。改完重启生效，一般用户无需打开。")
                .font(.caption).foregroundStyle(Color.textTertiary)
            Button("在文本编辑器中打开") { engine.openConfig() }.clickable()
        }
        .padding(20)
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}

#Preview {
    @Previewable @StateObject var engine = Engine()
    SettingsView()
        .environmentObject(engine)
        .frame(width: 1000, height: 700)
}
