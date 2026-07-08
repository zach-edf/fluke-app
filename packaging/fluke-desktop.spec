# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Fluke Community desktop app.

Builds a one-dir bundle of ``apps/desktop/main.py`` (console script
``fluke-desktop``). Works on Windows and macOS from the same spec; the
platform-specific bits (icon, .app bundle) are selected at build time.

Run from the repo root, e.g.::

    pyinstaller packaging/fluke-desktop.spec --noconfirm

The tricky bits this spec handles explicitly:

* PySide6 Qt plugins / QtCharts / QtAsyncio collection
* bleak platform backends (winrt on Windows, CoreBluetooth on macOS)
* the ``workflows/`` and ``plugins/`` data directories, shipped as bundled data
  and resolved at runtime via ``fluke_core.paths.bundled_data_dir``
* ``fluke_app.workflows`` package data (built-in workflow JSON)
"""

import os
import sys

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

# ``SPECPATH`` is injected by PyInstaller and points at this file's directory.
REPO_ROOT = os.path.dirname(os.path.abspath(SPECPATH))  # noqa: F821
PACKAGES = os.path.join(REPO_ROOT, "packages")

IS_WINDOWS = sys.platform.startswith("win")
IS_MACOS = sys.platform == "darwin"

APP_NAME = "FlukeCommunity"
ENTRY = os.path.join(REPO_ROOT, "apps", "desktop", "main.py")

# --- Data files ------------------------------------------------------------
datas = [
    (os.path.join(REPO_ROOT, "workflows"), "workflows"),
    (os.path.join(REPO_ROOT, "plugins"), "plugins"),
]
# Built-in workflow JSON shipped as importable package data (fluke_app.workflows).
datas += collect_data_files("fluke_app")

# --- Hidden imports --------------------------------------------------------
hiddenimports = []
# First-party packages: mostly imported statically, but the plugin loader and
# profile registry import some modules indirectly. Collect them wholesale so a
# missing lazy import never breaks a packaged build.
for pkg in (
    "fluke_core",
    "fluke_protocol",
    "fluke_ble",
    "fluke_app",
    "fluke_store",
    "fluke_plugins",
    "fluke_sdk",
):
    hiddenimports += collect_submodules(pkg)
hiddenimports += collect_submodules("apps")

# PySide6 pieces that are imported lazily inside functions and can be missed by
# static analysis.
hiddenimports += [
    "PySide6.QtCharts",
    "PySide6.QtAsyncio",
]

# --- bleak backends --------------------------------------------------------
# bleak selects its backend at runtime by platform. Collect everything for the
# active platform's backend plus the winrt projection modules on Windows.
bleak_datas, bleak_binaries, bleak_hiddenimports = collect_all("bleak")
datas += bleak_datas
binaries = list(bleak_binaries)
hiddenimports += bleak_hiddenimports

if IS_WINDOWS:
    for winrt_pkg in (
        "winrt.runtime",
        "winrt.windows.devices.bluetooth",
        "winrt.windows.devices.bluetooth.advertisement",
        "winrt.windows.devices.bluetooth.genericattributeprofile",
        "winrt.windows.devices.enumeration",
        "winrt.windows.devices.radios",
        "winrt.windows.foundation",
        "winrt.windows.foundation.collections",
        "winrt.windows.storage.streams",
    ):
        try:
            w_datas, w_binaries, w_hidden = collect_all(winrt_pkg)
        except Exception:  # pragma: no cover - defensive: some names are namespace-only
            continue
        datas += w_datas
        binaries += w_binaries
        hiddenimports += w_hidden

if IS_MACOS:
    hiddenimports += collect_submodules("bleak.backends.corebluetooth")

# --- Excludes --------------------------------------------------------------
# matplotlib is declared as a desktop extra but the live charts use QtCharts;
# nothing imports matplotlib, so keep it out of the bundle to save size.
excludes = [
    "matplotlib",
    "pandas",
    "pyarrow",
    "tkinter",
]

# --- Icon ------------------------------------------------------------------
ICON_DIR = os.path.join(REPO_ROOT, "packaging", "icons")
win_icon = os.path.join(ICON_DIR, "fluke.ico")
mac_icon = os.path.join(ICON_DIR, "fluke.icns")
icon = None
if IS_WINDOWS and os.path.exists(win_icon):
    icon = win_icon
elif IS_MACOS and os.path.exists(mac_icon):
    icon = mac_icon


block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[REPO_ROOT, PACKAGES],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

if IS_MACOS:
    app = BUNDLE(
        coll,
        name=f"{APP_NAME}.app",
        icon=mac_icon if os.path.exists(mac_icon) else None,
        bundle_identifier="community.fluke.desktop",
        info_plist={
            "CFBundleName": "Fluke Community",
            "CFBundleDisplayName": "Fluke Community",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "0.1.0",
            "NSHighResolutionCapable": True,
            # Required so macOS grants the app Bluetooth access (CoreBluetooth).
            "NSBluetoothAlwaysUsageDescription":
                "Fluke Community connects to your Fluke meter over Bluetooth Low Energy.",
            "NSBluetoothPeripheralUsageDescription":
                "Fluke Community connects to your Fluke meter over Bluetooth Low Energy.",
            "LSMinimumSystemVersion": "11.0",
        },
    )
