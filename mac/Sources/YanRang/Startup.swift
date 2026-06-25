import AppKit
import ServiceManagement

/*
 * [INPUT]: 依赖 AppKit 的 NSApp/激活策略、ServiceManagement 的 SMAppService、Foundation 的 UserDefaults
 * [OUTPUT]: 对外提供 Startup —— 开机自启(登录项)开关、静默启动偏好、窗口/后台形态切换
 * [POS]: YanRangUI 启动行为中枢，被 AppDelegate(静默判定)、SettingsView(开关 UI)、TrayView(打开主窗口回前台)消费
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

// ============================================================================
//  Startup —— 开机自启 + 静默启动：纯前端 App 行为偏好，不入引擎 config.yaml。
//
//  设计取舍(本质层)：这两个是「App 自身怎么被启动/呈现」，与「引擎怎么录音」正交，
//  故走 macOS 原生机制而非文件桥接——
//   · 开机自启 = 系统登录项 SMAppService.mainApp(macOS 13+)，系统自持久化，无需我们存。
//   · 静默启动 = UserDefaults(launchSilently)；启动时进「后台形态」，引擎照常在后台记录。
//
//  形态(哲学层)：App 只有两种姿态，用激活策略一刀切开，消除中间态——
//   · 前台形态 .regular   = 有 Dock + 窗口(常规使用)
//   · 后台形态 .accessory = 无 Dock + 仅菜单栏(静默记录)
//  「打开主窗口」永远把 App 拉回前台形态(幂等)：非静默用户调用是空操作，不改变其现有行为。
// ============================================================================
enum Startup {
    /// 静默启动偏好键。SettingsView 用 @AppStorage 同键直接双向绑定；此处供 AppDelegate 读判定。
    static let kSilent = "launchSilently"

    /// 静默启动是否开启(读 UserDefaults.standard，与 @AppStorage 同一存储)。
    static var silent: Bool { UserDefaults.standard.bool(forKey: kSilent) }

    /// 开机自启 = 把整个 .app 注册为系统登录项。状态由系统持久化，直接查/改 SMAppService。
    static var launchAtLogin: Bool {
        get { SMAppService.mainApp.status == .enabled }
        set {
            do {
                let svc = SMAppService.mainApp
                if newValue, svc.status != .enabled { try svc.register() }
                else if !newValue, svc.status == .enabled { try svc.unregister() }
            } catch {
                NSLog("Startup: 登录项\(newValue ? "注册" : "注销")失败 — \(error.localizedDescription)")
            }
        }
    }

    /// 进入后台形态：隐藏 Dock + 关主窗口，仅留菜单栏。引擎由 AppDelegate 另行拉起，不受影响。
    /// SwiftUI 主窗口可能晚于 didFinishLaunching 才创建 → 多拍补关，杜绝静默时窗口闪现残留。
    static func enterBackground() {
        NSApp.setActivationPolicy(.accessory)
        closeMainWindows()
        for delay in [0.0, 0.05, 0.2, 0.5] {
            DispatchQueue.main.asyncAfter(deadline: .now() + delay) { closeMainWindows() }
        }
    }

    /// 进入前台形态：恢复 Dock + 激活 App。供「打开主窗口」统一调用；非静默(已是 .regular)下幂等无副作用。
    static func enterForeground() {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    /// 关闭主窗口(标准 titled 窗口)，不动菜单栏弹窗(NSPanel)。
    /// close 不触发退出——AppDelegate.applicationShouldTerminateAfterLastWindowClosed 返回 false。
    private static func closeMainWindows() {
        for w in NSApp.windows where w.styleMask.contains(.titled) && !(w is NSPanel) {
            w.close()
        }
    }
}
