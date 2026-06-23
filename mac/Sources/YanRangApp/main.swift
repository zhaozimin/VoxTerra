/*
 * [INPUT]: 依赖 YanRangUI 库的 public YanRangApp
 * [OUTPUT]: 进程入口——拉起 SwiftUI 生命周期
 * [POS]: 可执行 target「YanRang」的唯一文件；UI/引擎全在 YanRangUI 库里(下沉以放行 Xcode 预览)
 * [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
 */

import YanRangUI

// 等价于在 YanRangApp 上写 @main；这里显式调用，让 App 类型可以待在库里被预览。
YanRangApp.main()
