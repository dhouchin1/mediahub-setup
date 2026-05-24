"""py2app build script — produces MediaHub Setup.app.

Usage:
    cd packaging/py2app
    pip install py2app
    python build_app.py py2app

The .app ends up at:
    packaging/py2app/dist/MediaHub Setup.app

To create a distributable DMG from it (requires create-dmg):
    brew install create-dmg
    create-dmg \
        --volname "MediaHub Setup" \
        --app-drop-link 450 200 \
        "dist/MediaHub Setup.dmg" \
        "dist/MediaHub Setup.app"

Notes:
  • LSUIElement=True hides the Dock icon (status-bar-only app).
  • argv_emulation=False — not needed for a menu-bar app, and enabling
    it causes deprecation warnings on macOS 14+.
  • --packages rumps is required because py2app doesn't detect it
    through normal import scanning (it uses ObjC introspection).
"""

from setuptools import setup  # py2app patches setuptools.setup

APP = ["app_main.py"]

OPTIONS = {
    "argv_emulation": False,
    "packages": ["mediahub_setup", "rumps", "flask", "waitress", "click", "requests"],
    "includes": [
        "jinja2",
        "markupsafe",
        "werkzeug",
        "itsdangerous",
        "blinker",
        "certifi",
        "charset_normalizer",
        "urllib3",
        "idna",
        "yaml",
    ],
    # Replace with a real 22×22 template PNG or a 1024×1024 ICNS.
    # "iconfile": "AppIcon.icns",
    "plist": {
        "CFBundleName": "MediaHub Setup",
        "CFBundleDisplayName": "MediaHub Setup",
        "CFBundleIdentifier": "com.dhouchin.mediahub-setup",
        "CFBundleVersion": "0.1.0",
        "CFBundleShortVersionString": "0.1.0",
        "NSHumanReadableCopyright": "© 2025 Dan Houchin. MIT License.",
        "LSUIElement": True,  # hide from Dock — status-bar only
        "NSHighResolutionCapable": True,
        "NSRequiresAquaSystemAppearance": False,  # allow dark mode
    },
    "resources": [],
}

setup(
    app=APP,
    data_files=[],
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
