"""Drive picker routes."""

from __future__ import annotations

import subprocess

from flask import Blueprint, redirect, render_template, request, url_for

from .. import drives as drive_lib
from .. import platform_detect, state

bp = Blueprint("drive", __name__, url_prefix="/drive")


def _selected_drive() -> drive_lib.DriveInfo | None:
    """Return a DriveInfo rebuilt from saved state, or None."""
    saved = state.get("drive")
    if not saved:
        return None
    return drive_lib.DriveInfo(
        name=saved.get("name", ""),
        mount_path=saved.get("mount_path", ""),
        filesystem=saved.get("filesystem", ""),
        total_bytes=int(saved.get("total_bytes", 0)),
        free_bytes=int(saved.get("free_bytes", 0)),
        writable=bool(saved.get("writable", False)),
    )


def _template_globals() -> dict:
    """Extra template variables shared by all drive views."""
    return {
        "drives_fmt_gb": drive_lib.fmt_gb,
        "is_macos": platform_detect.is_macos(),
    }


@bp.get("/")
def index():
    all_drives = drive_lib.list_drives()
    selected = _selected_drive()
    return render_template(
        "drive.html",
        step="drive",
        drives=all_drives,
        selected=selected,
        **_template_globals(),
    )


@bp.post("/refresh")
def refresh():
    """HTMX endpoint — returns just the drive-list partial."""
    all_drives = drive_lib.list_drives()
    return render_template(
        "_partials/drive_list.html",
        drives=all_drives,
        **_template_globals(),
    )


@bp.post("/pick")
def pick():
    mount_path = request.form.get("mount_path", "").strip()
    if not mount_path:
        return redirect(url_for("drive.index"))

    # Find the matching DriveInfo so we persist full metadata. If the path
    # isn't in the enumerated list (e.g. a manually-typed folder on a Linux
    # VPS), build a DriveInfo for it directly.
    all_drives = drive_lib.list_drives()
    chosen = next((d for d in all_drives if d.mount_path == mount_path), None)
    if chosen is None:
        chosen = drive_lib.drive_from_path(mount_path)

    if chosen is None or not chosen.writable:
        return redirect(url_for("drive.index"))

    state.set(
        "drive",
        {
            "name": chosen.name,
            "mount_path": chosen.mount_path,
            "filesystem": chosen.filesystem,
            "free_bytes": chosen.free_bytes,
            "total_bytes": chosen.total_bytes,
            "free_gb": chosen.free_gb,
            "total_gb": chosen.total_gb,
            "writable": chosen.writable,
        },
    )
    return redirect(url_for("settings.index"), code=303)


@bp.post("/open-disk-utility")
def open_disk_utility():
    """Launch macOS Disk Utility as a background process (no-op elsewhere)."""
    if platform_detect.is_macos():
        try:
            subprocess.Popen(["open", "-a", "Disk Utility"])
        except OSError:
            pass
    return redirect(url_for("drive.index"))
