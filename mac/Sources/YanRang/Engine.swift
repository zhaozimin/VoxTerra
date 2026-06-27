import Foundation
import SwiftUI

/*
 * [INPUT]: 依赖 Foundation/SwiftUI；读 Python sidecar 的 state.json(实时状态)、vault 的 *.md(笔记)、写 commands.json(命令)
 * [OUTPUT]: 对外 @MainActor Engine(ObservableObject) UI↔引擎契约、LogLine、ModelItem/ModelState、全局 ymdKey()
 * [POS]: YanRangUI 的数据中枢，各页面 View 经 @EnvironmentObject 消费；Phase2 文件桥接：读 state.json/vault，写 commands.json
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

struct LogLine: Identifiable, Equatable {
    let id: String      // 稳定 id(序号+时间):内容不变时 ForEach 不重建整列,免每拍刷新
    let time: String
    let text: String
}

// ============================================================================
//  本地语音模型（模型下载标签页用）
// ============================================================================
enum ModelState: Equatable {
    case notDownloaded
    case downloading(Double)   // 0...1 进度
    case downloaded
}

struct ModelItem: Identifiable {
    let id: String          // tiny/base/small/turbo
    let name: String        // 显示名
    let filename: String    // 引擎模型目录名(= modelName 比对，判断"使用中")
    let sizeText: String
    let desc: String        // 速度/准确度权衡一句话
    let recommended: Bool
    var state: ModelState
}

/// 统一的日期键：钉死公历 + en_US_POSIX + 本地时区，避免随系统区域(佛历/和历)漂移。
/// Engine / CalendarView / HistoryView 三处共用此实现，保证键空间同构(否则日历红点失配)。
func ymdKey(_ d: Date) -> String {
    let f = DateFormatter()
    f.calendar = Calendar(identifier: .gregorian)
    f.locale = Locale(identifier: "en_US_POSIX")
    f.timeZone = .current
    f.dateFormat = "yyyy-MM-dd"
    return f.string(from: d)
}

// ============================================================================
//  state.json 解码模型（与 Python _write_state() 的 schema 对齐，snake_case 直接命名）
// ============================================================================
private struct StateDTO: Decodable {
    let schema: Int
    let heartbeat: Double
    let version: String?
    let muted: Bool
    let live: Bool
    let count: Int
    let dropped: Int
    let sink: String?
    let err: String?
    let today_key: String?
    let today_file: String?
    let model: ModelDTO
    let speaker: SpeakerDTO
    let update: UpdateDTO?
    let paths: PathsDTO?
    let settings: SettingsDTO?

    struct SettingsDTO: Decodable {
        let ui_language: String?; let primary_language: String?; let secondary_language: String?
        let timezone: String?; let keywords: String?
        let vad_threshold: Double?; let min_speech_ms: Double?; let min_silence_ms: Double?
        let min_rms_dbfs: Double?; let speaker_threshold: Double?
        let speaker_min_verify_sec: Double?; let max_utterance_sec: Double?
    }
    struct ModelDTO: Decodable {
        let ready: Bool; let name: String
        let managed: Bool?; let downloading: Bool?; let pct: Int?; let dl_id: String?
        let result: String?; let result_id: String?      // ok/cancelled/fail + 哪一档(失败反馈用)
    }
    struct SpeakerDTO: Decodable {
        let enrolled: Bool; let gate_on: Bool; let last_score: Double?
        let threshold: Double?; let enrolling: Bool?
        let enroll_progress: Double?; let enroll_voiced: Double?; let enroll_quality: Double?
    }
    struct UpdateDTO: Decodable { let checked: Bool?; let latest: String? }
    struct PathsDTO: Decodable { let data_dir: String?; let vault: String?; let fallback: String?; let config: String? }
}

/// UI↔引擎契约。Phase 2 文件桥接：读 state.json + vault md 显示真实数据，写 commands.json 驱动引擎。
@MainActor
final class Engine: ObservableObject {
    // —— 实时状态（每拍由 reloadState() 从 state.json 刷新）——
    @Published var muted = false
    @Published var live = false
    @Published var count = 0
    @Published var dropped = 0
    @Published var modelReady = false
    @Published var modelName = "—"
    @Published var enrolled = false
    @Published var speakerOn = false
    @Published var lastScore: Double? = nil
    @Published var enrollConfirming = false      // 注册第一段:确认须知弹窗显示中(纯 UI,不涉引擎)
    @Published var enrolling = false             // 注册第二段:正在朗读采集(驱动朗读浮层)
    @Published var enrollProgress = 0.0          // 0...1 有效语音采集进度
    @Published var enrollVoiced = 0.0            // 已采集有效语音秒数(展示用)
    @Published var vault = ""
    @Published var updateLatest: String? = nil
    @Published var engineRunning = false        // heartbeat 新鲜度：false=引擎未跑/停摆，UI 可降级
    @Published var today: [LogLine] = []         // 今日记录（读 today_file/vault md）
    @Published private var historyDays: Set<String> = []   // 有笔记的日子（日历红点）

    // —— 设置回显（来自 state.settings，反映 config.yaml 已保存值）——
    @Published var cfgUILang = ""
    @Published var cfgPrimaryLang = ""
    @Published var cfgSecondaryLang = ""
    @Published var cfgTimezone = ""
    @Published var cfgKeywords = ""
    @Published var cfgParams: [String: Double] = [:]   // 键=config 键(vad_threshold 等)

    // 设置回显的"归属保护":用户刚改的字段在引擎确认前,不被陈旧轮询覆盖(消除切换闪烁)。
    // pendingSettings[key]=乐观值;轮询值 == 它即引擎已确认→清除放行;否则守住本地值,跳过覆盖。
    private var pendingSettings: [String: String] = [:]

    // 下载的"归属保护":刚点下载/续传的档,在引擎确认接手前守住 .downloading,不被轮询闪回"下载"。
    // 引擎对该档给出任何确定态(在下/已落盘/有结果)即撤销守护,交回轮询。同 pendingSettings 之理。
    private var pendingDownloads: Set<String> = []
    @Published var modelNote: String? = nil      // 模型区底部反馈("上次中断,已保留进度"等)

    // 各类乐观操作的"归属保护":引擎确认前守住乐观值,消除横跳/闪烁。引擎写回相同值即清除、交回轮询。
    private var pendingModelName: String? = nil   // 刚点"使用"的档名,等 s.model.name 对上才放行
    private var pendingMuted: Bool? = nil         // 刚点暂停/继续,等 s.muted 对上才放行
    private var pendingSpeakerOn: Bool? = nil     // 刚切声纹门,等 s.speaker.gate_on 对上才放行
    // 注册用"带超时的宽限"而非等 true:注册可能瞬间失败(没采到声音→引擎即刻 enrolling=false),
    // 若死等 true 会永远等不到 → 浮层永久卡住。故给乐观值一个截止时刻,到点/引擎接手即失效。
    private var pendingEnrollUntil: Date? = nil
    private var enrollCancelling = false          // 取消后:在引擎确认停下前,无视陈旧的 enrolling=true(消频闪)

    // 降频记忆:笔记/模型只在相关态变化时才重算,免每秒文件 IO + 整树重绘(静止时 CPU 应归零)。
    private var lastNoteCount = -1
    private var lastNoteTodayKey: String? = nil
    private var lastModelFp = ""

    let version = "1.2"

    // 四张模型卡（固定清单）；state 由 syncModels() 依 state.json + 目录扫描派生。
    @Published var models: [ModelItem] = [
        .init(id: "tiny",  name: "Whisper Tiny",  filename: "whisper-mlx-tiny",
              sizeText: "≈ 75 MB",  desc: "最快最省，准确度一般，随手速记够用", recommended: false, state: .notDownloaded),
        .init(id: "base",  name: "Whisper Base",  filename: "whisper-mlx-base",
              sizeText: "≈ 145 MB", desc: "速度快，日常口语足够", recommended: false, state: .notDownloaded),
        .init(id: "small", name: "Whisper Small", filename: "whisper-mlx-small",
              sizeText: "≈ 480 MB", desc: "速度与准确度均衡", recommended: false, state: .notDownloaded),
        .init(id: "turbo", name: "Whisper Turbo", filename: "whisper-mlx-turbo",
              sizeText: "≈ 1.5 GB", desc: "准确度高且快，离线版默认", recommended: true, state: .notDownloaded),
    ]

    var listening: Bool { !muted && live }

    // —— 文件桥接路径 ——
    private let bridge: URL              // ~/Library/Application Support/VoiceLog（或 env override）
    private var dataDir = ""             // state.paths.data_dir（模型目录扫描用）
    private var engineTodayKey = ""      // state.today_key（引擎时区的今天，历史判断用，避免系统日期错位）
    private var timer: Timer?

    private var stateURL: URL { bridge.appendingPathComponent("state.json") }
    private var cmdsURL:  URL { bridge.appendingPathComponent("commands.json") }
    private var vaultURL: URL? {
        vault.isEmpty ? nil : URL(fileURLWithPath: (vault as NSString).expandingTildeInPath)
    }

    init() {
        // 桥接目录：dev 用 env VOICELOG_DATA_DIR override；否则默认固定位置（与 Python BRIDGE 一致）。
        let fm = FileManager.default
        if let env = ProcessInfo.processInfo.environment["VOICELOG_DATA_DIR"], !env.isEmpty {
            bridge = URL(fileURLWithPath: (env as NSString).expandingTildeInPath)
        } else {
            bridge = fm.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/VoiceLog")
        }
        try? fm.createDirectory(at: bridge, withIntermediateDirectories: true)
        reloadState()
        timer = Timer.scheduledTimer(withTimeInterval: 1.0, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.reloadState() }
        }
    }

    deinit { timer?.invalidate() }

    func toggleMuted() {
        muted.toggle()                                  // 乐观更新
        pendingMuted = muted                            // 守护:引擎写回相同值前,别被陈旧轮询闪回
        send("toggle_mute")
    }

    // ========================================================================
    //  读：state.json → @Published（每秒一拍）
    // ========================================================================
    func reloadState() {
        guard let data = try? Data(contentsOf: stateURL),
              let s = try? JSONDecoder().decode(StateDTO.self, from: data) else {
            set(\.engineRunning, false)                 // 文件缺失/损坏 → 引擎没在跑
            return
        }
        set(\.engineRunning, Date().timeIntervalSince1970 - s.heartbeat < 6)   // 3 拍内有心跳=活
        // 暂停守护:刚点暂停/继续,等 s.muted 对上才放行(消除按一下闪回旧态)
        if let want = pendingMuted {
            if s.muted == want { pendingMuted = nil; set(\.muted, s.muted) }
        } else {
            set(\.muted, s.muted)
        }
        set(\.live, s.live)
        set(\.count, s.count)
        set(\.dropped, s.dropped)
        set(\.modelReady, s.model.ready)
        // 切换守护:刚点"使用"的档名,等引擎写回相同 name 才放行,否则守住乐观值(消除"使用中"横跳)
        if let want = pendingModelName {
            if s.model.name == want { pendingModelName = nil; set(\.modelName, s.model.name) }
        } else {
            set(\.modelName, s.model.name)
        }
        set(\.enrolled, s.speaker.enrolled)
        // 声纹门守护:刚切换,等 s.speaker.gate_on 对上才放行
        if let want = pendingSpeakerOn {
            if s.speaker.gate_on == want { pendingSpeakerOn = nil; set(\.speakerOn, s.speaker.gate_on) }
        } else {
            set(\.speakerOn, s.speaker.gate_on)
        }
        set(\.lastScore, s.speaker.last_score)
        // 注册守护(双向消闪):
        //  · 开始:点"注册"乐观置 true,在宽限期内保持(用截止时刻而非死等 true——注册可能瞬间失败,死等会永驻);
        //  · 取消:点"取消"乐观置 false,但引擎要 1~2 拍才停,陈旧的 enrolling=true 会把浮层拉回 → 频闪。
        //    故取消后置 enrollCancelling,在引擎确认停下(enrolling=false)前一律无视陈旧的 true。
        let engineEnrolling = s.speaker.enrolling ?? false
        if engineEnrolling { pendingEnrollUntil = nil }
        if !engineEnrolling { enrollCancelling = false }     // 引擎已停 → 撤销取消守护,交回轮询
        let optimisticEnroll = pendingEnrollUntil.map { Date() < $0 } ?? false
        set(\.enrolling, (engineEnrolling && !enrollCancelling) || optimisticEnroll)
        // 进度只在引擎真正在录该轮时取真值;乐观开窗的起步阶段/已结束 → 归零,
        // 免得重注册开头显示上一轮残留的 enroll_voiced(=20)→"0秒/采集完成"误闪。
        if engineEnrolling {
            set(\.enrollProgress, s.speaker.enroll_progress ?? 0)
            set(\.enrollVoiced, s.speaker.enroll_voiced ?? 0)
        } else {
            set(\.enrollProgress, 0)
            set(\.enrollVoiced, 0)
        }
        set(\.updateLatest, s.update?.latest)
        if let v = s.paths?.vault { set(\.vault, v) }
        if let d = s.paths?.data_dir { dataDir = d }
        engineTodayKey = s.today_key ?? ""
        if let g = s.settings {                       // 设置回显(LangTab 直接绑这些;Params/Keywords onAppear 取初值)
            echo("ui_language", g.ui_language ?? "", \.cfgUILang)
            echo("primary_language", g.primary_language ?? "", \.cfgPrimaryLang)
            echo("secondary_language", g.secondary_language ?? "", \.cfgSecondaryLang)
            echo("timezone", g.timezone ?? "", \.cfgTimezone)
            echo("keywords", g.keywords ?? "", \.cfgKeywords)
            set(\.cfgParams, [
                "vad_threshold": g.vad_threshold ?? 0.6,
                "min_speech_ms": g.min_speech_ms ?? 300,
                "min_silence_ms": g.min_silence_ms ?? 700,
                "min_rms_dbfs": g.min_rms_dbfs ?? -45,
                "speaker_threshold": g.speaker_threshold ?? 0.35,
                "speaker_min_verify_sec": g.speaker_min_verify_sec ?? 1.2,
                "max_utterance_sec": g.max_utterance_sec ?? 30,
            ])
        }
        // 模型卡:仅在引擎模型态有变(下载/就绪/切换/进度/pending)时才重算——免静止时每秒扫模型目录。
        let modelFp = "\(s.model.ready)|\(s.model.name)|\(s.model.downloading ?? false)|\(s.model.pct ?? 0)|\(s.model.dl_id ?? "")|\(s.model.result_id ?? "")|\(pendingDownloads.count)"
        if modelFp != lastModelFp { lastModelFp = modelFp; syncModels(s) }
        // 失败反馈:下载中断会留 .part,点「下载」即从断点续——明确告诉用户,别以为白下了
        switch s.model.result {
        case "fail":      set(\.modelNote, "上次下载中断,已保留进度。点对应档位的「下载」可从断点继续。")
        case "cancelled": set(\.modelNote, "已取消下载,进度已保留。点「下载」可从断点继续。")
        default:          set(\.modelNote, nil)
        }
        // 笔记:仅在有新记录(count 变)或跨天(today_key 变)时重读 → 免静止时每秒文件 IO + today 重绘。
        let todayKeyChanged = (s.today_key != lastNoteTodayKey)
        if s.count != lastNoteCount || todayKeyChanged {
            lastNoteCount = s.count
            lastNoteTodayKey = s.today_key
            refreshNotes(todayFile: s.today_file, scanHistory: todayKeyChanged)
        }
    }

    /// 仅在新值与当前不同才写入 @Published——避免无谓 objectWillChange 触发整树重算(性能命脉)。
    private func set<T: Equatable>(_ keyPath: ReferenceWritableKeyPath<Engine, T>, _ value: T) {
        if self[keyPath: keyPath] != value { self[keyPath: keyPath] = value }
    }

    /// 设置回显对账:pending 中的字段须等引擎回写相同值才放行,否则守住乐观值——消除切换闪烁。
    private func echo(_ key: String, _ incoming: String, _ keyPath: ReferenceWritableKeyPath<Engine, String>) {
        if let want = pendingSettings[key] {
            guard incoming == want else { return }      // 引擎尚未确认:守住本地乐观值,跳过覆盖
            pendingSettings.removeValue(forKey: key)     // 已确认:放行,恢复轮询接管
        }
        set(keyPath, incoming)
    }

    // ========================================================================
    //  写：动作 → commands.json（原子写 + 合并未消费队列）
    // ========================================================================
    private func send(_ cmd: String, _ args: [String: Any] = [:]) {
        var queue: [[String: Any]] = []
        if let d = try? Data(contentsOf: cmdsURL),
           let arr = try? JSONSerialization.jsonObject(with: d) as? [[String: Any]] {
            queue = arr                                 // 合并引擎尚未消费的命令
        }
        queue.append(["id": "u-\(Date().timeIntervalSince1970)", "cmd": cmd, "args": args])
        guard let data = try? JSONSerialization.data(withJSONObject: queue) else { return }
        try? data.write(to: cmdsURL, options: .atomic)  // 原子写，引擎永不读半截
    }

    // ---------------- 模型卡状态派生 ----------------
    private func syncModels(_ s: StateDTO) {
        for i in models.indices {
            let m = models[i]
            let engineDownloading = (s.model.downloading == true && s.model.dl_id == m.id)
            let onDisk = modelOnDisk(m.filename) || (m.filename == s.model.name && s.model.ready)
            // 引擎已对此档给出确定态(在下/已落盘/有结果)→ 撤销 pending 守护,交回轮询
            if engineDownloading || onDisk || s.model.result_id == m.id {
                pendingDownloads.remove(m.id)
            }
            let newState: ModelState
            if engineDownloading {
                newState = .downloading(Double(s.model.pct ?? 0) / 100)          // 正在下载的那张卡(真进度)
            } else if pendingDownloads.contains(m.id) {
                // 守护:引擎还没接手——保持本卡现有进度,绝不用全局 s.model.pct(那是上一个下载的残值,会闪 100%)
                if case .downloading(let p) = m.state { newState = .downloading(p) }
                else { newState = .downloading(0) }
            } else if onDisk {
                newState = .downloaded                                           // 已下载(含使用中)
            } else {
                newState = .notDownloaded
            }
            if models[i].state != newState { models[i].state = newState }        // 仅变化才写,免无谓 publish
        }
    }

    // 复刻 Python model_ready：目录里有 weights.*(≥1MB) 或 model.bin
    private func modelOnDisk(_ filename: String) -> Bool {
        guard !dataDir.isEmpty else { return false }
        let dir = URL(fileURLWithPath: dataDir)
            .appendingPathComponent("models").appendingPathComponent(filename)
        guard let items = try? FileManager.default.contentsOfDirectory(
            at: dir, includingPropertiesForKeys: [.fileSizeKey]) else { return false }
        for u in items {
            let n = u.lastPathComponent
            guard n.hasPrefix("weights.") || n == "model.bin" else { continue }
            let size = (try? u.resourceValues(forKeys: [.fileSizeKey]).fileSize) ?? 0
            if size >= 1_000_000 { return true }
        }
        return false
    }

    // ---------------- 模型命令（乐观更新 + 下命令；四档均托管）----------------
    func downloadModel(_ id: String) {
        guard let i = models.firstIndex(where: { $0.id == id }) else { return }
        if case .downloaded = models[i].state { return }
        if case .downloading = models[i].state { return }
        pendingDownloads.insert(id)        // 守护:引擎确认接手前别让轮询把卡片闪回"下载"
        modelNote = nil                     // 重下:清掉上次的失败提示
        models[i].state = .downloading(0)
        send("model_download", ["id": id])
    }

    func useModel(_ id: String) {
        guard let i = models.firstIndex(where: { $0.id == id }), models[i].state == .downloaded else { return }
        guard models[i].filename != modelName else { return }
        modelName = models[i].filename
        pendingModelName = models[i].filename   // 守护:引擎写回 config.model 前,"使用中"不被陈旧轮询横跳
        send("model_use", ["id": id])
    }

    func deleteModel(_ id: String) {
        guard let i = models.firstIndex(where: { $0.id == id }) else { return }
        if models[i].filename == modelName { return }     // 使用中不可删
        models[i].state = .notDownloaded
        send("model_delete", ["id": id])
    }

    // 取消下载:引擎下一拍停(慢网退避里也 ≤0.5s 响应);已下 .part 保留,下次点「下载」自动续。
    // 不乐观改卡态——让 syncModels 据 model_dl 落定,免与轮询对账打架(同 echo 闪烁之鉴)。
    func cancelModel(_ id: String) {
        guard let i = models.firstIndex(where: { $0.id == id }) else { return }
        if case .downloading = models[i].state { send("model_cancel") }
    }

    // ---------------- 设置类写命令（SettingsView 接线）----------------
    func setSpeakerGate(_ on: Bool)            { speakerOn = on; pendingSpeakerOn = on; send("speaker_gate", ["on": on]) }
    // 注册两段式:点"注册/重新注册"先弹确认须知 → "确定"才真正开录(跳朗读窗)、"取消"则关闭。
    func requestEnroll()                        { enrollConfirming = true }
    func dismissEnrollConfirm()                 { enrollConfirming = false }
    func confirmEnroll()                        { enrollConfirming = false; enrollVoice() }
    // 真正开录:乐观置 enrolling=true 立即弹朗读窗;宽限 5s 给引擎起注册,引擎接手则交回,否则到点失效
    // ——杜绝瞬间失败时浮层永驻。enrollCancelling 清零:新一轮注册不被上一次的取消守护误压。
    func enrollVoice()                          { pendingEnrollUntil = Date().addingTimeInterval(5); enrollCancelling = false; enrolling = true; send("enroll") }
    // 取消:乐观关浮层 + 置 enrollCancelling(引擎确认停下前无视陈旧 enrolling=true,消频闪);清宽限免又被乐观拉起。
    func cancelEnroll()                         { pendingEnrollUntil = nil; enrollCancelling = true; enrolling = false; send("cancel_enroll") }
    func setVault(_ path: String)               { send("set_vault", ["path": path]) }
    // 语言/时区:乐观回显 + 标记 pending(引擎确认前守住,防陈旧轮询闪烁) + 下命令(空串""=跟随系统/无)
    func setUILang(_ v: String)                 { cfgUILang = v; pendingSettings["ui_language"] = v; send("set_language", ["ui": v]) }
    func setPrimaryLang(_ v: String)            { cfgPrimaryLang = v; pendingSettings["primary_language"] = v; send("set_language", ["primary": v]) }
    func setSecondaryLang(_ v: String)          { cfgSecondaryLang = v; pendingSettings["secondary_language"] = v; send("set_language", ["secondary": v]) }
    func setTimezone(_ tz: String)              { cfgTimezone = tz; pendingSettings["timezone"] = tz; send("set_timezone", ["tz": tz]) }
    // 关键词不走「乐观回显 + pending 对账」：引擎必把规则规范化(`k = v`、去空行/注释/去重)后回写，
    // 与用户原文逐字节几乎永不相等 → 旧写法的 pendingSettings 守护会永久卡死，cfgKeywords 冻在用户
    // 输入值再不被引擎真值刷新(再进页 onAppear 显示的就成了发散的猜测值，甚至掩盖被静默丢弃的行)。
    // 关键词不参与实时回显(仅 onAppear 取一次)，无闪烁可防，故直接下命令、下一拍由引擎规范化值回显。
    func saveKeywords(_ text: String)           { send("save_keywords", ["text": text]) }
    func saveParams(_ vals: [String: Double])   { send("set_params", vals.mapValues { $0 as Any }) }
    func openConfig()                           { send("open_config") }
    func checkUpdate()                          { send("check_update") }

    // ========================================================================
    //  今日 / 历史 / 搜索：直接读 vault 的 *.md
    // ========================================================================
    private static let lineRE = try! NSRegularExpression(pattern: #"^- \*\*(\d{2}:\d{2})\*\* (.+)$"#)
    private static let dayRE  = try! NSRegularExpression(pattern: #"^\d{4}-\d{2}-\d{2}$"#)

    private func parseMd(_ url: URL) -> [LogLine] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [] }
        var out: [LogLine] = []
        for raw in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let s = String(raw)
            let r = NSRange(s.startIndex..., in: s)
            guard let m = Engine.lineRE.firstMatch(in: s, range: r),
                  let tr = Range(m.range(at: 1), in: s), let xr = Range(m.range(at: 2), in: s)
            else { continue }
            out.append(LogLine(id: "\(out.count)-\(s[tr])", time: String(s[tr]), text: String(s[xr])))
        }
        return out
    }

    private func refreshNotes(todayFile: String?, scanHistory: Bool) {
        let newToday: [LogLine]
        if let f = todayFile {
            newToday = parseMd(URL(fileURLWithPath: f))
        } else if let v = vaultURL {
            newToday = parseMd(v.appendingPathComponent(ymdKey(Date()) + ".md"))
        } else {
            newToday = []
        }
        set(\.today, newToday)
        if scanHistory { set(\.historyDays, scanDays()) }   // 历史日期集合只在跨天才变,无谓不扫目录
    }

    private func scanDays() -> Set<String> {
        guard let v = vaultURL,
              let items = try? FileManager.default.contentsOfDirectory(
                at: v, includingPropertiesForKeys: nil) else { return [] }
        var days = Set<String>()
        for u in items where u.pathExtension == "md" {
            let name = u.deletingPathExtension().lastPathComponent
            let r = NSRange(name.startIndex..., in: name)
            if Engine.dayRE.firstMatch(in: name, range: r) != nil { days.insert(name) }
        }
        return days
    }

    func lines(for date: Date) -> [LogLine] {
        let key = ymdKey(date)
        // 用引擎的今天键(引擎时区)判断，而非系统日期——否则跨时区时点"昨天"会错显今天缓存
        if !engineTodayKey.isEmpty && key == engineTodayKey { return today }
        guard let v = vaultURL else { return [] }
        return parseMd(v.appendingPathComponent(key + ".md"))
    }

    func historyDates() -> Set<String> { historyDays }

    func search(_ q: String) -> [(date: String, lines: [LogLine])] {
        let t = q.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty, let v = vaultURL else { return [] }
        return historyDays.sorted(by: >).compactMap { day in
            let hits = parseMd(v.appendingPathComponent(day + ".md")).filter { $0.text.contains(t) }
            return hits.isEmpty ? nil : (day, hits)
        }
    }
}
