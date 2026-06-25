# mac/ — 言壤 原生 SwiftUI 桌面端
> L2 | 父级: ../CLAUDE.md

V1 完整版的原生外壳：纯 SwiftUI 重写 UI，1:1 复刻 `desktop/`(已废弃的 Tauri 版) 的设计，
Python 引擎日后作 headless sidecar 接入（当前全 mock 数据）。SPM 编译 + 手工组装 .app，无需 Xcode GUI。

## 构建
config: SPM 双 target(Swift 5.9, macOS 14+)——**库 `YanRangUI`(全部 UI/引擎, 路径 `Sources/YanRang`) + 极薄可执行 `YanRang`(路径 `Sources/YanRangApp`, 仅 main.swift)**；Resources 用 `exclude` 不走 SPM
为何拆分: Xcode SwiftUI 实时预览(右侧画布)对**可执行 target**会报 `ENABLE_DEBUG_DYLIB`；代码沉到**库 target**后, 各文件已有的 `#Preview` 即可渲染(仅页面内容, 不含 NSWindow 工具栏/红绿灯/窗口圆角——那些只能 ⌘R 真窗口看)
入口: `YanRangApp` 留在库里(public, 去掉 @main)；`Sources/YanRangApp/main.swift` 一句 `YanRangApp.main()` 作进程入口
bundle.sh: `swift build` → 组装 `YanRang.app`(拷可执行 + **平铺 Resources/*.png 进 Contents/Resources** + 写 Info.plist)
资源加载: 用 `Bundle.main`(=Contents/Resources)而非 `Bundle.module`——后者在手工组装的 .app 里解析不到(分发即崩/图标空白)

## 成员清单
Package.swift: SPM 清单，声明库 `YanRangUI` + 可执行 `YanRang` 双 target 与 Resources `exclude`
bundle.sh: 编译并组装可运行 .app；把 Resources/*.png 平铺进 Contents/Resources 供 Bundle.main 读取；Info.plist 写 `NSAppSleepDisabled=YES`(常驻菜单栏前端退出 App Nap,闲置后图标/窗口即时响应)
Sources/YanRangApp/main.swift: 进程入口，`import YanRangUI` + `YanRangApp.main()`(代码全在库里以放行预览)

### Sources/YanRang/（= 库 YanRangUI 源码）
Theme.swift: 设计令牌，Figma 精确 hex + NSColor 动态明暗提供器，1:1 对齐 index.css :root/.dark
BrandIcon.swift: SVG path→SwiftUI Path 解析器(含圆弧采样) + GitHub/Obsidian/X 官方路径 + logo 资源加载
CalendarView.swift: 自定义月历(年/月下拉、红底选中、今日描红、记录红点)，复刻 shadcn calendar
Components.swift: card() 卡片底座 + clickable()(可点元素统一手型指针·Tahoe pointerStyle) + BreathingDot 呼吸灯 + StatTile + ConfigRow
App.swift: public YanRangApp(被 main.swift 启动) + 统一工具栏窗口 + 顶栏(品牌/CenteredNav 窗口居中导航·**收敛前隐藏淡入根治开屏颤抖**:位置连续两拍不变才显示、2.5s 兜底/状态丸) + 注册两段式浮层(EnrollConfirmSheet 确认须知 → EnrollOverlay 朗读窗:显稿子+倒计时+末尾"可再读"提示+取消) + MenuBarExtra 托盘 + EngineLauncher(Process 拉起同包内 headless 引擎 Contents/MacOS/VoiceLog；开发用 env VOICELOG_PYTHON/ENGINE;已有引擎在跑则不重复拉起) + AppDelegate(关窗=隐藏托盘不退出、退出停引擎、静默启动进后台形态见 Startup.swift)
Startup.swift: 开机自启 + 静默启动(纯前端 App 行为,不入引擎 config)。开机自启=系统登录项 SMAppService.mainApp(系统自持久化);静默启动=UserDefaults(launchSilently),启动时进「后台形态」.accessory(无 Dock+关主窗,引擎照常后台记录);「打开主窗口」统一回「前台形态」.regular(幂等,不破坏非静默用户现有行为)
Engine.swift: UI↔引擎契约(@MainActor ObservableObject)，Phase1 mock，Phase2 换读/写 sidecar；内含全局 ymdKey(公历钉死)供三处共用 + 本地模型 models[ModelItem]/下载·取消(cancelModel)·切换·删除 + 声纹注册(enrollVoice/cancelEnroll + enrolling/进度回显)。**「归属保护」统一消除"乐观写被陈旧轮询闪回"**:pendingSettings/echo(语言时区)、pendingDownloads(下载卡,且守护期不用全局 pct 残值→防闪 100%)、pendingModelName(切换"使用中"不横跳)、pendingMuted/pendingSpeakerOn(暂停/声纹门)、pendingEnrollUntil(注册用带超时宽限,防瞬间失败时浮层永驻);modelNote 显下载中断/取消反馈。**性能命脉:reloadState 全字段 diff 赋值(值不变不 publish)+笔记/模型仅相关态变化时重读+LogLine 稳定 id → 杜绝每秒全树重绘(静止 CPU 归零)**
HomeView.swift: 首页(状态英雄区 + 统计/配置 + 今日实时流)
HistoryView.swift: 历史(搜索置顶 + 左大日历右内容卡 + 全历史搜索)
SettingsView.swift: 设置(页内胶囊标签：语言时区/模型下载/保存位置/关键词/参数/配置文件/启动)；启动页=开机自启+静默启动两开关(走 Startup.swift,纯前端偏好,@AppStorage/SMAppService)；语言时区页=固定宽(192)自定义 Menu 下拉(复刻 Tauri w-48 select)；模型下载页=模型卡+下载/取消(✕,留进度续传)/使用(切换)/删除按钮+进度+中断反馈条,驱动 Engine.models
AboutView.swift: 关于(真 App logo + 介绍 + 作者链接，真品牌图标)
TrayView.swift: 菜单栏弹窗——Quiet Dark 卡片化(系统 MenuBarExtra(.window) 即玻璃面板,内铺前景 5% 叠层圆角卡,禁双层面板)。摘要卡(黑底 App logo Asset.logoDark+言壤+版本号同行+录音中/已暂停+自绘绿轨道开关 QuietSwitch)/状态卡(本地模型·声纹 绿点在线/橙点缺失)/打开主窗口卡(经 Startup.enterForeground 回前台形态)/链接卡(作者三链接转中性:globe+Obsidian/GitHub 矢量,单绿铁律)/退出红卡。内含 QuietSwitch/OpenMainCard/QuitCard/LinkRow 私有组件 + quietCard/actionCardBackground 卡片底座
Resources/: AppLogo.png(关于页彩色红底 logo) + AppLogoDark.png(托盘摘要卡黑底 logo,裁自 VoiceLog_iconmaster.png 满铺) + TrayIcon.png(菜单栏单色模板图标)

## 设计要点（为何这样）
- 隐藏系统标题栏(.hiddenTitleBar) + 自绘顶栏：上下同底色、无分割线、红绿灯悬浮其上 → 真正的"统一工具栏"
- 颜色用 NSColor 动态提供器：组件零判断自动明暗，且精确还原 Figma hex(系统语义色还原不准)
- 日历自建而非 DatePicker：原生控件无法放大/标红点/精确控制选中今日配色
- 品牌图标走 SVG 路径矢量渲染：任意尺寸清晰、可染色，免外部依赖与位图

法则: 成员完整·一行一文件·父级链接·技术词前置

[PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
