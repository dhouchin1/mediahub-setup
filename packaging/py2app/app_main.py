"""py2app entry-point bootstrap.

py2app needs a concrete script file as the 'app' target. This file is
intentionally thin — all logic lives in mediahub_setup.menubar.

Build:
    cd packaging/py2app
    python build_app.py py2app
"""

from mediahub_setup.menubar import main

if __name__ == "__main__":
    main()
