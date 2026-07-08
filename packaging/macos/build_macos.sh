#!/usr/bin/env bash
#
# Build the macOS .app bundle for the Fluke Community desktop app and package it
# into a .dmg for distribution.
#
# NOTE: This path is CI-validated only. It has not been run on a local macOS
# machine by the author. Run it on macOS (locally or in GitHub Actions) to
# produce artifacts.
#
# Usage:
#   packaging/macos/build_macos.sh            # build .app + .dmg
#   packaging/macos/build_macos.sh --no-dmg   # build .app only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

APP_NAME="FlukeCommunity"
APP_DISPLAY="Fluke Community"
VERSION="0.1.0"
MAKE_DMG=1

for arg in "$@"; do
  case "${arg}" in
    --no-dmg) MAKE_DMG=0 ;;
    *) echo "Unknown argument: ${arg}" >&2; exit 2 ;;
  esac
done

echo "==> Building PyInstaller .app bundle"
python -m PyInstaller packaging/fluke-desktop.spec --noconfirm --clean

APP_BUNDLE="dist/${APP_NAME}.app"
if [[ ! -d "${APP_BUNDLE}" ]]; then
  echo "Expected .app bundle not found: ${APP_BUNDLE}" >&2
  exit 1
fi

echo "==> Running smoke test"
python packaging/smoke_test.py

if [[ "${MAKE_DMG}" -eq 0 ]]; then
  echo "==> Skipping .dmg (--no-dmg). App bundle at ${APP_BUNDLE}."
  exit 0
fi

echo "==> Creating .dmg"
DMG_DIR="dist/dmg"
DMG_PATH="dist/${APP_NAME}-${VERSION}.dmg"
rm -rf "${DMG_DIR}" "${DMG_PATH}"
mkdir -p "${DMG_DIR}"
cp -R "${APP_BUNDLE}" "${DMG_DIR}/${APP_DISPLAY}.app"
# Drag-to-install affordance: a symlink to /Applications inside the disk image.
ln -s /Applications "${DMG_DIR}/Applications"

hdiutil create \
  -volname "${APP_DISPLAY}" \
  -srcfolder "${DMG_DIR}" \
  -ov \
  -format UDZO \
  "${DMG_PATH}"

rm -rf "${DMG_DIR}"
echo "==> Done. Disk image at ${DMG_PATH}."
echo "    (Unsigned / un-notarized: users must right-click > Open on first launch.)"
