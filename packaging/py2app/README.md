# MediaHub Setup — macOS .app bundle

Builds a self-contained `MediaHub Setup.app` that lives in the menu bar
and manages the wizard server without a Terminal window.

## Quick build

```bash
# From the repo root:
pip install 'mediahub-setup[menubar]' py2app

cd packaging/py2app
python build_app.py py2app
open dist/"MediaHub Setup.app"
```

## Icon

py2app will embed whatever you point `iconfile` at in `build_app.py`.
To add a proper icon:

1. Design a 1024×1024 PNG (or 22×22 template PNG for the menu-bar icon).
2. Convert to ICNS with:
   ```bash
   mkdir MyIcon.iconset
   sips -z 1024 1024 icon.png --out MyIcon.iconset/icon_1024x1024.png
   iconutil -c icns MyIcon.iconset
   ```
3. Drop `MyIcon.icns` here and set `"iconfile": "MyIcon.icns"` in `build_app.py`.

## Distributable DMG

```bash
brew install create-dmg
create-dmg \
    --volname "MediaHub Setup" \
    --app-drop-link 450 200 \
    "dist/MediaHub Setup.dmg" \
    "dist/MediaHub Setup.app"
```

## GitHub Actions

The workflow at `.github/workflows/build-app.yml` builds the .app and
attaches the DMG as a release asset automatically on each GitHub Release.
