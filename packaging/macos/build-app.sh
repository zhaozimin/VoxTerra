#!/bin/bash
# ============================================================================
#  言壤 · 完整 App 统一构建
#  以 PyInstaller 的 VoiceLog.app(引擎+Python运行时)为底座，嫁接 SwiftUI 前端：
#  主可执行=YanRang(SwiftUI 窗口+菜单栏)，由它拉起同包内引擎(Contents/MacOS/VoiceLog, headless)。
#  Developer ID 由内向外深签 → DMG。公证另跑 notarize.sh(需 Apple 凭据)。
#  前置：先跑 build.sh 的 PyInstaller 步骤生成 dist/VoiceLog.app。
#  [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
# ============================================================================
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"            # packaging/macos
PROJ="$(cd "$HERE/../.." && pwd)"
MAC="$PROJ/mac"
DIST="$PROJ/dist"
APP="$DIST/VoiceLog.app"
ENT="$HERE/entitlements.plist"
DEV_ID="${DEV_ID:-Developer ID Application: Zimin Zhao (NNB86K8P8S)}"

[ -d "$APP" ] || { echo "!! 先生成 $APP (PyInstaller, 见 build.sh 第2步)"; exit 1; }
VER="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$APP/Contents/Info.plist")"

echo "==> [1/5] swift build release"
cd "$MAC"
swift build -c release
SWIFT_EXE="$MAC/.build/release/YanRang"
DYLIB="$(find -L "$MAC/.build/release" \( -name "YanRangUI.dylib" -o -name "libYanRangUI.dylib" \) | head -1)"
[ -x "$SWIFT_EXE" ] || { echo "!! 无 Swift 可执行"; exit 1; }
[ -n "$DYLIB" ] || { echo "!! 无 YanRangUI.dylib"; exit 1; }

echo "==> [2/5] 嫁接 SwiftUI 进 $APP"
cp "$SWIFT_EXE" "$APP/Contents/MacOS/YanRang"
mkdir -p "$APP/Contents/Frameworks"
cp "$DYLIB" "$APP/Contents/Frameworks/"
install_name_tool -id "@rpath/$(basename "$DYLIB")" "$APP/Contents/Frameworks/$(basename "$DYLIB")"
install_name_tool -add_rpath "@executable_path/../Frameworks" "$APP/Contents/MacOS/YanRang" 2>/dev/null || true
# 品牌 PNG 平铺进 Contents/Resources —— 运行期唯一真相源(NSImage.bundled 经 Bundle.main 读取)。
# 必须成功:缺图 = 启动图标空白/降级，故 set -euo pipefail 下不再吞错(过去 `2>/dev/null||true` 掩盖缺失)。
cp "$MAC"/Sources/YanRang/Resources/*.png "$APP/Contents/Resources/"

echo "==> [3/5] 改 Info.plist：主入口=YanRang，去 LSUIElement(显示窗口/Dock)"
PL="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleExecutable YanRang" "$PL"
/usr/libexec/PlistBuddy -c "Delete :LSUIElement" "$PL" 2>/dev/null || true
# bundle id / 版本 / 麦克风用途串 / 品牌名 沿用 PyInstaller(spec)写好的，机器名不动。

echo "==> [4/5] 由内向外深签(含新加 Swift exe/dylib;内嵌引擎单独带 entitlements)"
MACHO=()
while IFS= read -r -d '' f; do
  file -b "$f" 2>/dev/null | grep -q "Mach-O" && MACHO+=("$f")
done < <(find "$APP/Contents" -type f -print0)
echo "    Mach-O 共 ${#MACHO[@]} 个"
printf '%s\0' "${MACHO[@]}" | xargs -0 codesign --force --timestamp --options runtime -s "$DEV_ID"
find "$APP/Contents" -name "*.framework" -type d -print0 \
  | xargs -0 -I{} codesign --force --timestamp --options runtime -s "$DEV_ID" {} 2>/dev/null || true
codesign --force --timestamp --options runtime --entitlements "$ENT" -s "$DEV_ID" "$APP/Contents/MacOS/VoiceLog"
codesign --force --timestamp --options runtime --entitlements "$ENT" -s "$DEV_ID" "$APP/Contents/MacOS/YanRang"
codesign --force --timestamp --options runtime --entitlements "$ENT" -s "$DEV_ID" "$APP"
echo "    校验:" && codesign --verify --deep --strict --verbose=2 "$APP" 2>&1 | tail -2 || true

echo "==> [5/5] 打 DMG"
DMG="$DIST/言壤-$VER.dmg"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/言壤.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "言壤 $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
codesign --force --timestamp -s "$DEV_ID" "$DMG"
echo ""
echo "✅ 完整 App 构建完成:"
echo "   App: $APP (主入口 YanRang + 内嵌引擎 VoiceLog)"
echo "   DMG: $DMG ($(du -h "$DMG" | cut -f1))"
