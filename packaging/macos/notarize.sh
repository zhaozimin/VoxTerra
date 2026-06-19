#!/bin/bash
# ============================================================================
#  VoiceLog · macOS 公证 + 装订 (Apple notarytool)
#  前提:已跑过 build.sh 生成 dist/VoiceLog.app(已签名)。
#  凭据(任选其一):
#    A) 钥匙串 profile:  xcrun notarytool store-credentials voicelog-notary \
#                          --apple-id <你的AppleID> --team-id NNB86K8P8S --password <专用密码>
#       然后直接运行: ./notarize.sh
#    B) 环境变量一次性:  APPLE_ID=.. APPLE_PASSWORD=.. ./notarize.sh
#  产出:公证并装订(stapled)的 dist/VoiceLog.app 与 dist/VoiceLog-<ver>.dmg(可离线验证)。
#  [PROTOCOL]: 变更时更新此头部，然后检查 CLAUDE.md
# ============================================================================
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PROJ="$(cd "$HERE/../.." && pwd)"
VER="$(grep -m1 'CFBundleShortVersionString' "$HERE/VoiceLog.spec" | sed -E 's/.*"([0-9.]+)".*/\1/')"
DEV_ID="${DEV_ID:-Developer ID Application: Zimin Zhao (NNB86K8P8S)}"
TEAM_ID="${TEAM_ID:-NNB86K8P8S}"
PROFILE="${NOTARY_PROFILE:-voicelog-notary}"
DIST="$PROJ/dist"
APP="$DIST/VoiceLog.app"
DMG="$DIST/VoiceLog-$VER.dmg"
ZIP="$DIST/VoiceLog.zip"

[ -d "$APP" ] || { echo "!! 未找到 $APP,请先运行 build.sh"; exit 1; }

# --- 凭据组装:优先环境变量(顺带写入钥匙串 profile),否则用已存的 profile ---
if [ -n "${APPLE_ID:-}" ] && [ -n "${APPLE_PASSWORD:-}" ]; then
  echo "==> 写入钥匙串公证凭据 profile=$PROFILE"
  xcrun notarytool store-credentials "$PROFILE" \
    --apple-id "$APPLE_ID" --team-id "$TEAM_ID" --password "$APPLE_PASSWORD" >/dev/null
fi
AUTH=(--keychain-profile "$PROFILE")

submit() {  # $1=待提交文件
  xcrun notarytool submit "$1" "${AUTH[@]}" --wait
}

echo "==> [1/5] 压缩 App 提交公证"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"
submit "$ZIP"

echo "==> [2/5] 装订 App(写入离线票据)"
xcrun stapler staple "$APP"

echo "==> [3/5] 用已装订的 App 重建 DMG"
rm -f "$DMG"
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "VoiceLog $VER" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
codesign --force --timestamp -s "$DEV_ID" "$DMG"

echo "==> [4/5] 提交 DMG 公证并装订"
submit "$DMG"
xcrun stapler staple "$DMG"

echo "==> [5/5] 最终验证(应显示 accepted / source=Notarized Developer ID)"
xcrun stapler validate "$DMG" || true
spctl -a -vvv -t install "$DMG" 2>&1 | head -3 || true
spctl -a -vvv "$APP" 2>&1 | head -3 || true
rm -f "$ZIP"

echo ""
echo "✅ 公证完成,可分发: $DMG  ($(du -h "$DMG" | cut -f1))"
