#!/bin/bash
# 打包 "AI元数据检测器.app" 为可分发的 .dmg。用法： ./make_dmg.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/AI元数据检测器.app"
DMG="$DIR/AI元数据检测器.dmg"
VOL="AI 元数据检测器"

[ -d "$APP" ] || { echo "未找到 $APP，请先运行 ./build.sh"; exit 1; }

echo "==> 准备临时目录 ..."
STAGE="$(mktemp -d)"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"     # 方便用户拖入 Applications

echo "==> 生成 DMG ..."
rm -f "$DMG"
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
rm -rf "$STAGE"

echo "✅ 打包完成： $DMG"
echo "   大小： $(du -h "$DMG" | cut -f1)"
