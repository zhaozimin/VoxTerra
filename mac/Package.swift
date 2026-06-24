// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "YanRang",
    platforms: [.macOS(.v14)],
    // ── products 声明 YanRangUI 为 library product ──
    // 关键：Xcode 为每个 library product 生成独立 scheme；
    // 预览系统使用 YanRangUI scheme（库 target）而非 YanRang scheme（可执行 target），
    // 绕过 Xcode 17 JIT 预览对可执行 target 强制要求 ENABLE_DEBUG_DYLIB 的限制。
    products: [
        .library(name: "YanRangUI", type: .dynamic, targets: ["YanRangUI"])
    ],
    targets: [
        // ── 库 target：全部 UI/引擎代码 ──
        .target(
            name: "YanRangUI",
            path: "Sources/YanRang",
            // Resources 不走 SPM(故意不生成 Bundle.module)：手工组装的 .app 里 Bundle.module 访问器
            // 找不到资源包会 fatalError 杀进程(分发即崩)。改由 bundle.sh/build-app.sh 平铺 PNG 进
            // Contents/Resources, 运行期统一走 Bundle.main —— 单一真相源, 不崩。
            exclude: ["Resources"]
        ),
        // ── 可执行 target：极薄入口 ──
        // 仅 main.swift 一句 YanRangApp.main()。产物名仍为 YanRang(bundle.sh 依赖此名)。
        .executableTarget(
            name: "YanRang",
            dependencies: ["YanRangUI"],
            path: "Sources/YanRangApp"
        )
    ]
)
