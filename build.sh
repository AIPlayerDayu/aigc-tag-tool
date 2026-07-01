#!/bin/bash
# 从 src/ 构建 "AI元数据检测器.app"。用法： ./build.sh
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/AI元数据检测器.app"
SRC="$DIR/src"
PB=/usr/libexec/PlistBuddy

echo "==> 生成图标 ..."
python3 "$SRC/make_icon.py" || echo "（跳过图标）"

echo "==> 编译 AppleScript ..."
rm -rf "$APP"
osacompile -o "$APP" "$SRC/main.applescript"

echo "==> 拷贝检测脚本与前端 ..."
cp "$SRC/detect.py" "$SRC/server.py" "$SRC/index.html" "$APP/Contents/Resources/"
chmod +x "$APP/Contents/Resources/detect.py" "$APP/Contents/Resources/server.py"
[ -f "$SRC/icon.icns" ] && cp "$SRC/icon.icns" "$APP/Contents/Resources/droplet.icns"

echo "==> 写入 Info.plist ..."
PLIST="$APP/Contents/Info.plist"
$PB -c "Set :CFBundleName AI元数据检测器" "$PLIST"
$PB -c "Add :CFBundleDisplayName string AI元数据检测器" "$PLIST" 2>/dev/null || \
  $PB -c "Set :CFBundleDisplayName AI元数据检测器" "$PLIST"
$PB -c "Set :CFBundleIdentifier com.local.aimetadetector" "$PLIST" 2>/dev/null || \
  $PB -c "Add :CFBundleIdentifier string com.local.aimetadetector" "$PLIST"
$PB -c "Add :CFBundleDocumentTypes array" "$PLIST" 2>/dev/null || true
$PB -c "Add :CFBundleDocumentTypes:0 dict" "$PLIST"
$PB -c "Add :CFBundleDocumentTypes:0:CFBundleTypeName string 'Image or Video'" "$PLIST"
$PB -c "Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer" "$PLIST"
$PB -c "Add :CFBundleDocumentTypes:0:LSHandlerRank string Alternate" "$PLIST"
$PB -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes array" "$PLIST"
i=0; for uti in public.image public.movie public.jpeg public.png; do
  $PB -c "Add :CFBundleDocumentTypes:0:LSItemContentTypes:$i string $uti" "$PLIST"; i=$((i+1))
done

echo "==> 移除多余权限描述 ..."
for k in NSHomeKitUsageDescription NSAppleMusicUsageDescription NSCalendarsUsageDescription \
         NSSiriUsageDescription NSCameraUsageDescription NSMicrophoneUsageDescription \
         NSRemindersUsageDescription NSContactsUsageDescription NSPhotoLibraryUsageDescription \
         NSSystemAdministrationUsageDescription NSAppleEventsUsageDescription; do
  $PB -c "Delete :$k" "$PLIST" 2>/dev/null || true
done

echo "==> 代码签名（ad-hoc）..."
codesign --force --deep -s - "$APP" || true

LSREG=/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister
"$LSREG" -f "$APP" || true

echo "✅ 构建完成： $APP"
