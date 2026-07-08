# Application icons

Drop platform icon files here before building release artifacts:

- `fluke.ico` — Windows icon (used by the PyInstaller EXE and the Inno Setup installer)
- `fluke.icns` — macOS icon (used by the `.app` bundle)
- `fluke.png` — optional source master (1024x1024 recommended)

The build is intentionally tolerant: if these files are absent, PyInstaller
builds with the default icon and the installer scripts skip the icon step. Add
real branded icons here when they are available.

## Generating from a PNG master

macOS (`iconutil` ships with Xcode command line tools):

```bash
mkdir fluke.iconset
sips -z 16 16   fluke.png --out fluke.iconset/icon_16x16.png
sips -z 32 32   fluke.png --out fluke.iconset/icon_16x16@2x.png
sips -z 128 128 fluke.png --out fluke.iconset/icon_128x128.png
sips -z 256 256 fluke.png --out fluke.iconset/icon_256x256.png
sips -z 512 512 fluke.png --out fluke.iconset/icon_512x512.png
iconutil -c icns fluke.iconset -o fluke.icns
```

Windows (with ImageMagick):

```bash
magick fluke.png -define icon:auto-resize=16,32,48,64,128,256 fluke.ico
```
