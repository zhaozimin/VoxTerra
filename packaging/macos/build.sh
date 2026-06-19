#!/bin/bash
# ============================================================================
#  VoiceLog · macOS 构建 + 签名 + 打 DMG (本机运行,需 Developer ID 证书在钥匙串)
#  产出: dist/VoiceLog.app(已硬化签名) + dist/VoiceLog-<ver>.dmg
#  公证另跑 notarize.sh(需 Apple ID 专用密码)。
#  [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"            # packaging/macos
PROJ="$(cd "$HERE/../.." && pwd)"               # 仓库根
VENV="${VENV:-$HOME/voicelog-venv}"
PY="$VENV/bin/python"
VER="$(grep -m1 'CFBundleShortVersionString' "$HERE/VoiceLog.spec" | sed -E 's/.*"([0-9.]+)".*/\1/')"
DEV_ID="${DEV_ID:-Developer ID Application: Zimin Zhao (NNB86K8P8S)}"
ENT="$HERE/entitlements.plist"
DIST="$PROJ/dist"
APP="$DIST/VoiceLog.app"
DMG="$DIST/VoiceLog-$VER.dmg"

echo "==> [1/5] 清理旧产物"
rm -rf "$PROJ/build" "$DIST"

echo "==> [2/5] PyInstaller 打包 (torch/mlx/speechbrain,耗时数分钟)"
cd "$PROJ"
"$PY" -m PyInstaller --clean --noconfirm --distpath "$DIST" \
      --workpath "$PROJ/build" "$HERE/VoiceLog.spec"
[ -d "$APP" ] || { echo "!! 打包失败:未生成 $APP"; exit 1; }

echo "==> [3/5] 由内向外深度签名(硬化运行时)"
# 先签所有嵌套 mach-O(dylib/so),再签框架,最后签 .app 主体——顺序错了公证必挂。
find "$APP/Contents" \( -name "*.dylib" -o -name "*.so" \) -type f -print0 \
  | xargs -0 -I{} codesign --force --timestamp --options runtime -s "$DEV_ID" {} 2>/dev/null || true
# 嵌套 .framework(若有)逐个签
find "$APP/Contents" -name "*.framework" -type d -print0 \
  | xargs -0 -I{} codesign --force --timestamp --options runtime -s "$DEV_ID" {} 2>/dev/null || true
# 主可执行 + 整个 bundle(带 entitlements)
codesign --force --timestamp --options runtime --entitlements "$ENT" \
         -s "$DEV_ID" "$APP/Contents/MacOS/VoiceLog"
codesign --force --timestamp --options runtime --entitlements "$ENT" \
         -s "$DEV_ID" "$APP"

echo "==> [4/5] 校验签名"
codesign --verify --deep --strict --verbose=2 "$APP"
echo "    (spctl 在公证前必然报 rejected,属正常)"
spctl -a -vvv "$APP" 2>&1 | head -3 || true

echo "==> [5/5] 打 DMG"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "VoiceLog $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
codesign --force --timestamp -s "$DEV_ID" "$DMG"

echo ""
echo "✅ 构建完成:"
echo "   App : $APP"
echo "   DMG : $DMG  ($(du -h "$DMG" | cut -f1))"
echo "   下一步:运行 notarize.sh 做公证(需 Apple ID 专用密码)。"
