#!/bin/bash
# 言壤 SwiftUI：SPM 编译 → 组装可运行的 .app bundle（无需 Xcode GUI）
set -e
cd "$(dirname "$0")"
CONFIG=${1:-debug}

echo "==> swift build ($CONFIG)"
swift build -c "$CONFIG"

APP="YanRang.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp ".build/$CONFIG/YanRang" "$APP/Contents/MacOS/YanRang"

# 动态库嵌入（type:.dynamic 编译产物；含 AppKit 符号，预览不需再弱链接）
mkdir -p "$APP/Contents/Frameworks"
DYLIB=$(find ".build/$CONFIG" -name "YanRangUI.dylib" -o -name "libYanRangUI.dylib" 2>/dev/null | head -1)
if [ -n "$DYLIB" ]; then
    cp "$DYLIB" "$APP/Contents/Frameworks/"
    # 把 dylib 的 install name 改为 @rpath，让可执行文件通过 rpath 找到它
    install_name_tool -id "@rpath/$(basename $DYLIB)" "$APP/Contents/Frameworks/$(basename $DYLIB)"
    install_name_tool -add_rpath "@executable_path/../Frameworks" "$APP/Contents/MacOS/YanRang" 2>/dev/null || true
fi
# SPM 资源包 + PNG 平铺（Bundle.module / Bundle.main 双路径）
cp -r ".build/$CONFIG/YanRangUI_YanRangUI.bundle" "$APP/Contents/Resources/" 2>/dev/null || true
cp Sources/YanRang/Resources/*.png "$APP/Contents/Resources/"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>言壤</string>
  <key>CFBundleDisplayName</key><string>言壤</string>
  <key>CFBundleExecutable</key><string>YanRang</string>
  <key>CFBundleIdentifier</key><string>com.zhaozimin.voicelog.swift</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>0.9.5</string>
  <key>CFBundleVersion</key><string>0.9.5</string>
  <key>LSMinimumSystemVersion</key><string>14.0</string>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

echo "==> bundled $APP"
