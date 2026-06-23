import SwiftUI
import AppKit

/*
 * [INPUT]: 依赖 Engine、各页面 View、Color 令牌、Asset.trayIcon
 * [OUTPUT]: 对外 public YanRangApp(由 Sources/YanRangApp/main.swift 启动)、统一工具栏 RootView、分段导航 Segmented、窗口居中导航 CenteredNav/NavCenterer(收敛淡入)、状态丸 StatusPill、声纹注册两段式浮层 EnrollConfirmSheet/EnrollOverlay、EngineLauncher(拉起 sidecar 引擎)、AppDelegate(关窗隐藏托盘/退出停引擎)
 * [POS]: YanRangUI 库的外壳层，1:1 复刻 desktop/src/App.tsx 的「标题栏合一」布局；入口下沉到库以放行 SwiftUI 预览
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

// @main 不在此处：代码沉到库 target(YanRangUI) 以放行预览，启动改由可执行 target 的 main.swift 调 YanRangApp.main()。
public struct YanRangApp: App {
    public init() {}
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var engine = Engine()

    public var body: some Scene {
        // 主窗口：标题设空(根治切页时系统重画出第二个「言壤」的竞态——无文字可渲染)；
        // 原生统一工具栏 → 红绿灯与工具栏项同行；隐藏工具栏背景/分割线 + 窗口底色=页面底色 → 上下一体。
        // app 菜单名由 Info.plist 的 CFBundleName=言壤 提供，不受影响。
        Window("", id: "main") {
            RootView().environmentObject(engine)
        }
        .windowToolbarStyle(.unified)   // 更高的统一工具栏，容纳放大的导航 + 居中红绿灯
        .defaultSize(width: 1000, height: 700)

        // 菜单栏托盘：真 logo(模板图标) + 自定义弹窗(文字可彩色)
        MenuBarExtra {
            TrayView().environmentObject(engine)
        } label: {
            Image(nsImage: Asset.trayIcon)
        }
        .menuBarExtraStyle(.window)
    }
}

// ============================================================================
//  EngineLauncher —— 把 Python headless 引擎作为 sidecar 拉起/停掉
//  开发：读 env VOICELOG_PYTHON + VOICELOG_ENGINE；打包：用 bundle 内嵌 sidecar(Phase 3C)。
//  拉起前先看 state.json 心跳——已有引擎在跑(菜单栏/launchd/残留)则不重复拉起(防双开抢麦/双写)。
// ============================================================================
final class EngineLauncher {
    private var process: Process?

    private var bridge: URL {
        if let env = ProcessInfo.processInfo.environment["VOICELOG_DATA_DIR"], !env.isEmpty {
            return URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        }
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/VoiceLog")
    }

    private var engineAlreadyRunning: Bool {
        let url = bridge.appendingPathComponent("state.json")
        guard let d = try? Data(contentsOf: url),
              let o = try? JSONSerialization.jsonObject(with: d) as? [String: Any],
              let hb = o["heartbeat"] as? Double else { return false }
        return Date().timeIntervalSince1970 - hb < 6
    }

    func start() {
        guard process?.isRunning != true else { return }
        guard !engineAlreadyRunning else { return }       // 已有引擎在跑 → 不重复拉起
        let env = ProcessInfo.processInfo.environment
        let exe: String
        var args: [String] = []
        // 打包：同一 .app 内嵌的 PyInstaller 引擎(Contents/MacOS/VoiceLog)；headless 由下方 env 触发。
        let bundled = Bundle.main.bundleURL.appendingPathComponent("Contents/MacOS/VoiceLog").path
        if FileManager.default.isExecutableFile(atPath: bundled) {
            exe = bundled
        } else if let py = env["VOICELOG_PYTHON"], let script = env["VOICELOG_ENGINE"] {
            exe = py; args = [script]                      // 开发：venv python + 源码引擎
        } else {
            NSLog("EngineLauncher: 无内嵌 sidecar 且未设 VOICELOG_PYTHON/VOICELOG_ENGINE，跳过拉起")
            return
        }
        let p = Process()
        p.executableURL = URL(fileURLWithPath: exe)
        p.arguments = args
        var e = env
        e["VOICELOG_HEADLESS"] = "1"
        p.environment = e
        do { try p.run(); process = p }
        catch { NSLog("EngineLauncher 启动失败: \(error)") }
    }

    func stop() {
        if process?.isRunning == true { process?.terminate() }
        process = nil
    }
}

// ============================================================================
//  AppDelegate —— 关窗=隐藏到托盘(不退出) + 启动拉起引擎 + 退出停引擎
// ============================================================================
final class AppDelegate: NSObject, NSApplicationDelegate {
    let launcher = EngineLauncher()

    func applicationDidFinishLaunching(_ note: Notification) {
        launcher.start()                                  // App 起 → 引擎起(若尚无引擎在跑)
    }
    // 关最后一个窗口不退出 → App 留在菜单栏(隐藏到托盘)，从 TrayView「打开主窗口」重开
    func applicationShouldTerminateAfterLastWindowClosed(_ s: NSApplication) -> Bool { false }
    func applicationWillTerminate(_ note: Notification) {
        launcher.stop()                                   // App 退 → 引擎随之停
    }
}

// ============================================================================
//  四个页面
// ============================================================================
enum Page: CaseIterable, Identifiable {
    case home, history, settings, about
    var id: Self { self }
    var title: String {
        switch self {
        case .home: "首页"; case .history: "历史"; case .settings: "设置"; case .about: "关于"
        }
    }
    var icon: String {
        switch self {
        case .home: "house"; case .history: "calendar"; case .settings: "gearshape"; case .about: "info.circle"
        }
    }
}

struct RootView: View {
    @EnvironmentObject var engine: Engine
    @State private var page: Page = .home

    var body: some View {
        // .toolbar 挂在稳定父节点(ZStack)而非切页的 switch 结果上：
        // 切页只换内部页面视图，工具栏项 identity 恒定 → NSToolbar 不重建、测量层不重生 → 无闪跳。
        ZStack {
            Color.appBg
            content
        }
        .frame(minWidth: 880, minHeight: 600)
        .background(WindowConfigurator())                 // 窗口底色=appBg，消除工具栏接缝
        .overlay { if engine.enrollConfirming { EnrollConfirmSheet() } }   // 注册第一段：确认须知(确定/取消)
        .overlay { if engine.enrolling { EnrollOverlay() } }               // 注册第二段：朗读稿子+倒计时+取消
        .toolbar { unifiedBar }
        .toolbarBackground(.hidden, for: .windowToolbar)   // 去背景=去分割线
    }

    // 页面切换：纯内容，不挂任何工具栏项。
    @ViewBuilder private var content: some View {
        switch page {
        case .home: HomeView()
        case .history: HistoryView()
        case .settings: SettingsView()
        case .about: AboutView()
        }
    }

    // 统一工具栏：品牌(让出红绿灯) / 导航(钉死窗口几何中线) / 状态丸(右对齐)，1:1 复刻 Tauri 三段语义。
    // 每项隐藏 Tahoe「共享液态玻璃」底：系统给每个 ToolbarItem 套一层胶囊玻璃，与自绘圆角不重合 → 视觉「框中框」。
    // .toolbarBackground(.hidden) 只去整条工具栏底，去不掉 per-item 这层，故用 .sharedBackgroundVisibility。
    @ToolbarContentBuilder
    private var unifiedBar: some ToolbarContent {
        if #available(macOS 26.0, *) {
            ToolbarItem(placement: .navigation)    { BrandTitle() }.sharedBackgroundVisibility(.hidden)
            ToolbarItem(placement: .principal)     { CenteredNav(page: $page) }.sharedBackgroundVisibility(.hidden)
            ToolbarItem(placement: .primaryAction) { StatusPill() }.sharedBackgroundVisibility(.hidden)
        } else {
            ToolbarItem(placement: .navigation)    { BrandTitle() }
            ToolbarItem(placement: .principal)     { CenteredNav(page: $page) }
            ToolbarItem(placement: .primaryAction) { StatusPill() }
        }
    }
}

// 配置窗口：①底色=appBg 消接缝 ②清空系统标题 ③把红绿灯垂直居中到标题栏中线。
// 居中需在布局完成后做，且监听 resize 重做，防止被 AppKit 复位。
private struct WindowConfigurator: NSViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async { context.coordinator.attach(v.window) }
        return v
    }
    func updateNSView(_ v: NSView, context: Context) {
        DispatchQueue.main.async { context.coordinator.attach(v.window) }
    }

    final class Coordinator {
        private weak var window: NSWindow?
        private var observer: NSObjectProtocol?

        func attach(_ w: NSWindow?) {
            guard let w else { return }
            harden(w)                 // 每次更新都做(幂等)：防 SwiftUI 切页时把标题复位成「言壤」
            ensureOnScreen(w)         // 防窗口被恢复到屏幕外坐标(换更小显示器/外接屏断开)→ 进程在跑却看不见
            centerTrafficLights()
            guard w !== window else { return }   // —— 以下仅在窗口首次出现/被更换时做一次 ——
            if let o = observer { NotificationCenter.default.removeObserver(o); observer = nil }
            window = w
            observer = NotificationCenter.default.addObserver(    // 重绑到新窗口(旧窗口关闭→托盘重开会换实例)
                forName: NSWindow.didResizeNotification, object: w, queue: .main
            ) { [weak self] _ in self?.centerTrafficLights() }
            // 布局/坐标恢复可能晚于此刻完成 → 多次延迟补做(每窗口仅排一次，避免每次刷新无谓堆积)
            for d in [0.05, 0.2, 0.5, 1.0] {
                DispatchQueue.main.asyncAfter(deadline: .now() + d) { [weak self] in
                    guard let self, let w = self.window else { return }
                    self.centerTrafficLights(); self.ensureOnScreen(w)
                }
            }
        }

        // 窗口整体落在所有屏幕可见区之外时居中拉回，杜绝"打开却看不见"。
        private func ensureOnScreen(_ w: NSWindow) {
            guard !NSScreen.screens.contains(where: { $0.visibleFrame.intersects(w.frame) }) else { return }
            w.center()
        }

        // 幂等的窗口外观强制：隐藏系统标题、透明标题栏、底色=appBg
        private func harden(_ w: NSWindow) {
            w.titleVisibility = .hidden
            w.title = ""
            w.titlebarAppearsTransparent = true
            w.backgroundColor = NSColor(name: nil) { ap in
                ap.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? NSColor(hex: "0a0a0a") : NSColor(hex: "fafafa")
            }
        }

        deinit { if let o = observer { NotificationCenter.default.removeObserver(o) } }

        private func centerTrafficLights() {
            guard let w = window else { return }
            for type in [NSWindow.ButtonType.closeButton, .miniaturizeButton, .zoomButton] {
                guard let b = w.standardWindowButton(type), let sv = b.superview else { continue }
                var f = b.frame
                f.origin.y = (sv.bounds.height - f.height) / 2   // 居中到整条标题栏高度
                b.setFrameOrigin(f.origin)
            }
        }
    }
}

// 品牌：言壤. + 版本（工具栏左侧，紧随红绿灯）
private struct BrandTitle: View {
    @EnvironmentObject var engine: Engine
    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            Text("言壤").font(.system(size: 15, weight: .semibold))
            Text(".").font(.system(size: 15, weight: .semibold)).foregroundStyle(Color.brand)
            Text("v\(engine.version)").font(.system(size: 12))
                .foregroundStyle(Color.textTertiary).padding(.leading, 6)
        }
    }
}

// 分段导航胶囊（bg/sunken 容器 + 选中 bg/surface + 阴影）
private struct Segmented: View {
    @Binding var page: Page
    var body: some View {
        HStack(spacing: 2) {
            ForEach(Page.allCases) { p in SegItem(p: p, page: $page) }
        }
        .padding(3)
        .background(RoundedRectangle(cornerRadius: 9, style: .continuous).fill(Color.sunken))
        .fixedSize()   // 防止工具栏压缩导致「首页」被截成「...」
    }
}

private struct SegItem: View {
    let p: Page
    @Binding var page: Page
    @State private var hover = false
    private var active: Bool { page == p }

    var body: some View {
        Button { page = p } label: {
            HStack(spacing: 6) {
                Image(systemName: p.icon).font(.system(size: 13, weight: .medium))
                Text(p.title).font(.system(size: 14, weight: .medium))
            }
            .padding(.horizontal, 14).padding(.vertical, 6)
            .fixedSize()
            .foregroundStyle(active || hover ? Color.appFg : Color.textTertiary)
            .background(
                // 选中=实心卡片+阴影;未选中悬停=半透明卡底,明确"可点"
                RoundedRectangle(cornerRadius: 6, style: .continuous)
                    .fill(active ? Color.card : (hover ? Color.card.opacity(0.55) : .clear))
                    .shadow(color: active ? .black.opacity(0.12) : .clear, radius: 1, y: 1)
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .onHover { hover = $0 }
        .animation(.easeOut(duration: 0.12), value: hover)
        .clickable()
    }
}

// ============================================================================
//  CenteredNav —— 导航胶囊钉死「窗口几何中线」，切页/缩放/聚焦全程不漂
//
//  设计语义 1:1 复刻 Tauri(desktop/src/App.tsx)：absolute left:50%; -translate-x-1/2
//  —— 导航相对【整窗宽度】居中，不受品牌/状态宽度、不受 NSToolbar 摆放策略影响。
//
//  双保险断绝漂移：
//   ① .frame(maxWidth: .infinity) 让 principal【撑满可用区】→ full-width 项不会被
//      NSToolbar 在切页时重新摆放（漂移的根源是 content-sized 小项被重新居中）→ 容器位置恒定。
//   ② NavCenterer 实测容器横向中点、用 offset 把胶囊精确推到 winW/2；并以 page 为依赖，
//      切页必触发 updateNSView → 重测校正（即便 ① 未完全稳住也能拉回正中）。
//  offset 施加在胶囊上、不动测量层 → 不自指、无反馈环。零魔法数，居中是几何必然。
// ============================================================================
private struct CenteredNav: View {
    @Binding var page: Page
    @State private var navOffset: CGFloat = 0
    @State private var navReady = false                      // 收敛前隐藏:开屏 settle 期的跳动一律不可见
    var body: some View {
        ZStack {
            Segmented(page: $page)
                .offset(x: navOffset)
                .opacity(navReady ? 1 : 0)                   // 位置稳定前不画;稳定后淡入(永不让用户看到颤抖)
                .animation(.easeOut(duration: 0.18), value: navReady)
        }
        .frame(maxWidth: .infinity)                          // 撑满可用区 → 不随切页被重新摆放
        .background(NavCenterer(offset: $navOffset, ready: $navReady))
    }
}

// 测量「导航容器」在窗口内容区坐标系的横向中点，算出推到窗口几何中线所需 offset。
//
// 切页漂移根因(已确诊)：旧实现里 principal 是 content-sized 小项，切页时被 NSToolbar 重新摆到
// 偏右，而切页【无任何重测信号】(didResize 只缩放发、layout() 纯移位不触发) → offset 停旧值 → 跟漂。
// 本版：① 容器 maxWidth 撑满 → 不再被重摆；② page 入参 → 切页必触发 updateNSView → 重测兜底。
// 坐标用 AppKit convert(to: contentView)(比 SwiftUI .global 跨 NSToolbar host 可靠)。
private struct NavCenterer: NSViewRepresentable {
    @Binding var offset: CGFloat
    @Binding var ready: Bool         // 位置收敛后置 true → 胶囊淡入(开屏 settle 期保持隐藏,杜绝可见颤抖)
    func makeCoordinator() -> Coordinator { Coordinator(offset: $offset, ready: $ready) }
    func makeNSView(context: Context) -> NSView {
        let v = NSView()
        DispatchQueue.main.async { context.coordinator.attach(v) }
        return v
    }
    func updateNSView(_ v: NSView, context: Context) {
        DispatchQueue.main.async { context.coordinator.attach(v) }
    }

    final class Coordinator {
        private let offset: Binding<CGFloat>
        private let ready: Binding<Bool>
        private weak var view: NSView?
        private weak var window: NSWindow?
        private var observer: NSObjectProtocol?
        private var stableCount = 0                       // 连续 N 拍位置不再变 = 收敛
        init(offset: Binding<CGFloat>, ready: Binding<Bool>) { self.offset = offset; self.ready = ready }

        func attach(_ v: NSView) {
            view = v
            measure()                                    // 立即测一次
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.03) { [weak self] in self?.measure() }
            let w = v.window
            guard w !== window else { return }           // 以下仅在首次出现/换窗时做一次
            if let o = observer { NotificationCenter.default.removeObserver(o); observer = nil }
            window = w
            if let w {
                observer = NotificationCenter.default.addObserver(    // 缩放信号
                    forName: NSWindow.didResizeNotification, object: w, queue: .main
                ) { [weak self] _ in self?.measure() }
            }
            // 开屏密集补测:窗口/工具栏/状态丸布局逐拍落定,直到位置连续两拍不变(收敛)才淡入。
            for d in [0.0, 0.05, 0.1, 0.18, 0.28, 0.4, 0.6, 0.9, 1.3, 2.0] {
                DispatchQueue.main.asyncAfter(deadline: .now() + d) { [weak self] in self?.measure() }
            }
            // 兜底:万一始终不收敛(异常),2.5s 后也强制显示,杜绝导航永久隐身。
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak self] in
                guard let self else { return }
                self.measure()
                if !self.ready.wrappedValue { self.ready.wrappedValue = true }
            }
        }

        // 容器中点 → 窗口内容区中线 的水平位移。content 与 titlebar 同对齐窗口横轴，故中线一致。
        // offset 施加在胶囊上、不动本测量层 → boxCenter 与 offset 无关，无反馈环。
        // 收敛门:位置仍在动(>2px)就应用新值并清零计数(此时胶囊仍隐藏,跳动不可见);
        // 连续两拍 ≤2px 不变 = 布局已 settle → 置 ready 淡入。死区 2px 同时滤掉子像素舍入抖。
        func measure() {
            guard let v = view, let content = v.window?.contentView else { return }
            let boxCenter = v.convert(v.bounds, to: content).midX
            let target = (content.bounds.width / 2) - boxCenter
            if abs(target - offset.wrappedValue) > 2.0 {
                offset.wrappedValue = target
                stableCount = 0
            } else {
                stableCount += 1
                if stableCount >= 2 && !ready.wrappedValue { ready.wrappedValue = true }
            }
        }

        deinit { if let o = observer { NotificationCenter.default.removeObserver(o) } }
    }
}

// 状态丸：圆角胶囊 + 彩色圆点 + 文字（聆听中/已暂停/准备中）
struct StatusPill: View {
    @EnvironmentObject var engine: Engine
    private var color: Color { engine.listening ? .ok : (engine.muted ? Color.textTertiary : .warn) }
    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(color).frame(width: 9, height: 9)
            Text(engine.muted ? "已暂停" : engine.listening ? "聆听中" : "准备中")
                .font(.system(size: 13, weight: .medium))
        }
        .padding(.horizontal, 12).padding(.vertical, 6)
        // 同心：半径=窗口外角(16) − 内缩(≈8) = 8pt continuous。放弃满胶囊——胶囊半径=高/2 是自适应，
        // 不知道窗口外角是 16，丸高一变就漂、永远凑不出同心。显式钉死半径，同心是设计出来的。
        .background(RoundedRectangle(cornerRadius: 8, style: .continuous).fill(Color.card))
        .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).stroke(Color.hairline, lineWidth: 1))
        .fixedSize()
    }
}

// 注册稿子:照着读即可建好声纹(说明 + 再读提示都并入正文,读出来就是引导,稿子下方不再另设提示)。
private let kEnrollScript =
    "你好，我正在为这台设备注册我的声音。从现在起，它只会记录我本人说的话，" +
    "自动忽略身边其他人的交谈和外放的视频声音。请用平时聊天的音量，自然地把这段话读完就好，" +
    "中间停顿一下也没关系。它只采集你的声音，与你读的内容无关。读完了倒计时还没结束，从头再读一遍就行。"

// 浮层通用底座:暗化背景 + 居中卡片
private struct EnrollCard<Content: View>: View {
    let width: CGFloat
    @ViewBuilder var content: Content
    var body: some View {
        ZStack {
            Color.black.opacity(0.45).ignoresSafeArea()
            VStack(spacing: 16) { content }
                .padding(32).frame(width: width)
                .background(RoundedRectangle(cornerRadius: 16, style: .continuous).fill(Color.card))
                .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).stroke(Color.hairline, lineWidth: 1))
                .shadow(color: .black.opacity(0.3), radius: 24, y: 8)
        }
    }
}

// ============================================================================
//  注册第一段：确认须知 —— 「确定」开始朗读、「取消」关闭(两键真实生效)
// ============================================================================
private struct EnrollConfirmSheet: View {
    @EnvironmentObject var engine: Engine
    var body: some View {
        EnrollCard(width: 380) {
            Image(systemName: "checkmark.shield.fill").font(.system(size: 34)).foregroundStyle(Color.brand)
            Text("声纹注册").font(.system(size: 18, weight: .semibold))
            Text("点击确认后，照着稿子读就可以了。")
                .font(.system(size: 14)).foregroundStyle(Color.textSecondary)
                .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 12) {
                Button("取消") { engine.dismissEnrollConfirm() }
                    .buttonStyle(.bordered).controlSize(.large).clickable()
                Button("确定") { engine.confirmEnroll() }
                    .buttonStyle(.borderedProminent).controlSize(.large).tint(Color.brand).clickable()
            }
            .padding(.top, 4)
        }
    }
}

// ============================================================================
//  注册第二段：朗读窗 —— 显示稿子 + 倒计时(读出声才倒数) + 进度 + 随时取消
//  enrolling 期间覆盖全窗;采够「有效语音」即由引擎收尾、浮层自动消失。
// ============================================================================
private struct EnrollOverlay: View {
    @EnvironmentObject var engine: Engine
    private let targetSec = 20.0     // = 引擎 ENROLL_VOICED_SEC
    private var remaining: Int { max(0, Int(ceil(targetSec - engine.enrollVoiced))) }   // 倒计时:还需朗读秒数
    var body: some View {
        EnrollCard(width: 480) {
            HStack(spacing: 8) {
                Image(systemName: "mic.fill").foregroundStyle(Color.brand)
                Text("请照着下面的文字朗读").font(.system(size: 16, weight: .semibold))
            }
            // 稿子
            Text(kEnrollScript)
                .font(.system(size: 16)).lineSpacing(6)
                .foregroundStyle(Color.appFg)
                .multilineTextAlignment(.leading).fixedSize(horizontal: false, vertical: true)
                .padding(16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(RoundedRectangle(cornerRadius: 10).fill(Color.sunken))
            // (说明与"再读一遍"提示已并入上面的朗读稿子,此处不再重复)
            // 倒计时 + 进度
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("\(remaining)").font(.system(size: 40, weight: .bold, design: .rounded))
                    .monospacedDigit().foregroundStyle(remaining == 0 ? Color.ok : Color.brand)
                Text("秒").font(.system(size: 15)).foregroundStyle(Color.textSecondary)
            }
            Text(remaining == 0 ? "采集完成，正在生成声纹…" : "还需朗读约这么久（读出声才会倒数）")
                .font(.caption).foregroundStyle(Color.textTertiary)
            ProgressView(value: min(1, engine.enrollProgress)).frame(width: 320)
            Button("取消") { engine.cancelEnroll() }
                .buttonStyle(.bordered).controlSize(.large).padding(.top, 4).clickable()
        }
    }
}

#Preview("首页") {
    @Previewable @StateObject var engine = Engine()
    HomeView()
        .environmentObject(engine)
        .frame(width: 1000, height: 700)
}

#Preview("完整导航") {
    @Previewable @StateObject var engine = Engine()
    RootView()
        .environmentObject(engine)
        .frame(width: 1000, height: 700)
}
