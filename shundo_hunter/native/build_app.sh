#!/bin/zsh
set -euo pipefail

project_root="${0:A:h:h:h}"
native_root="$project_root/shundo_hunter/native"
build_root="$project_root/build/shundo-hunter"
app_root="$project_root/dist/Shundo Hunter.app"
contents_root="$app_root/Contents"
macos_root="$contents_root/MacOS"
resources_root="$contents_root/Resources"

mkdir -p "$build_root" "$macos_root" "$resources_root"
mkdir -p "$build_root/module-cache"
export CLANG_MODULE_CACHE_PATH="$build_root/module-cache"
export SWIFT_MODULECACHE_PATH="$build_root/module-cache"

xcrun swiftc \
  "$native_root/main.swift" \
  "$native_root/ShundoHunterApp.swift" \
  "$native_root/MacNotificationBridge.swift" \
  "$native_root/PokeXperienceBridge.swift" \
  -framework AppKit \
  -framework ApplicationServices \
  -framework WebKit \
  -o "$build_root/ShundoHunter"

cp "$build_root/ShundoHunter" "$macos_root/ShundoHunter"
xcrun swiftc "$native_root/CatchScreenReader.swift" -framework Vision -framework ImageIO \
  -o "$build_root/CatchScreenReader"
cp "$build_root/CatchScreenReader" "$macos_root/CatchScreenReader"
xcrun swiftc "$native_root/VisionSupport.swift" -framework Security -framework ImageIO -framework CoreGraphics \
  -o "$build_root/VisionSupport"
cp "$build_root/VisionSupport" "$macos_root/VisionSupport"
cp "$native_root/Info.plist" "$contents_root/Info.plist"
# Keep the iPhone runner's original signature inside an archive: macOS deep
# signing must never re-sign its nested iOS executable. The owned supervisor
# extracts this into a private temporary directory and invokes Xcode's runner.
controller_products="$project_root/build/wda/DerivedData/Build/Products"
controller_plans=("$controller_products"/*.xctestrun(N))
if (( ${#controller_plans} != 1 )); then
  echo "Build the signed Hunter WDA controller before packaging the Mac app." >&2
  exit 1
fi
ditto -c -k --keepParent "$controller_products" "$resources_root/phone-controller.zip"
rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude 'data/' \
  --exclude 'tests/' \
  --exclude 'native/' \
  --exclude 'design/' \
  "$project_root/shundo_hunter/" \
  "$resources_root/shundo_hunter/"

# Isolate the newer native Wi-Fi transport from the established USB install.
mkdir -p "$resources_root/wifi-runtime/pymobiledevice3-master"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' \
  "$project_root/build/wifi-runtime/pymobiledevice3-master/pymobiledevice3/" \
  "$resources_root/wifi-runtime/pymobiledevice3-master/pymobiledevice3/"
cp "$project_root/build/wifi-runtime/pymobiledevice3-master/LICENSE" \
  "$resources_root/wifi-runtime/pymobiledevice3-master/LICENSE"
rsync -a --delete --exclude '__pycache__/' --exclude '*.pyc' --exclude 'bin/' \
  "$project_root/build/wifi-runtime/dependencies/" "$resources_root/wifi-runtime/dependencies/"

codesign_identity="${SHUNDO_CODESIGN_IDENTITY:-}"
if [[ -z "$codesign_identity" ]]; then
  codesign_identity="$(
    security find-identity -v -p codesigning 2>/dev/null \
      | sed -n 's/.*"\(Apple Development:[^"]*\)".*/\1/p' \
      | head -n 1
  )"
fi
if [[ -z "$codesign_identity" ]]; then
  echo "No Apple Development signing identity was found." >&2
  echo "Set SHUNDO_CODESIGN_IDENTITY to a stable signing identity and rebuild." >&2
  exit 1
fi

codesign --force --deep --options runtime --sign "$codesign_identity" "$app_root"
# Confirm that the signed bundle exposes a stable designated requirement. Some
# local Apple Development chains are accepted for launch but are not trusted by
# codesign's offline certificate-policy verifier, so do not make that unrelated
# policy check a build blocker.
codesign -dr - "$app_root" >/dev/null
echo "$app_root"
