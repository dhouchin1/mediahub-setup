"""Repair / resume mode.

Inspects the current state on disk (wizard state file, ~/mediahub/
docker-compose.yml, running containers) and reports what's complete,
what's partially done, and what's missing. Lets the user resume from
any step or re-run only the wiring tasks that failed.

This is the answer to: "I closed the wizard halfway / a wiring task
failed — what do I do?"
"""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for

from .. import docker_ops, installer, services, state, wiring_runner

bp = Blueprint("repair", __name__, url_prefix="/repair")


def _detect_progress() -> dict:
    """Aggregate the current state of a partial install.

    Returns:
        dict with keys:
          - has_state: bool — any saved wizard state at all?
          - drive: dict | None
          - settings: dict | None
          - install_dir_exists: bool
          - compose_exists: bool
          - running_containers: list[str]  (mediahub-*)
          - wiring_complete: bool
          - failed_tasks: list[dict]  (from saved wiring state)
          - missing_optional_wiring: list[str] — services in settings but not yet wired
    """
    snap = state.snapshot()
    drive = snap.get("drive")
    settings = snap.get("settings")
    wiring_meta = snap.get("wiring") or {}

    install_dir = installer.INSTALL_DIR
    compose_path = install_dir / "docker-compose.yml"

    running: list[str] = []
    if docker_ops.docker_available():
        running = [c["name"] for c in docker_ops.list_containers() if c["state"] == "running"]

    enabled = (settings or {}).get("enabled_services") or []
    planned = wiring_runner.planned_task_names(enabled)
    done_tasks = wiring_meta.get("tasks") or []
    done_names_ok = {t.get("name") for t in done_tasks if t.get("status") == "ok"}
    failed_tasks = [t for t in done_tasks if t.get("status") == "failed"]
    missing_tasks = [n for n in planned if n not in done_names_ok]

    return {
        "has_state": bool(snap),
        "drive": drive,
        "settings": settings,
        "install_dir_exists": install_dir.exists(),
        "compose_exists": compose_path.exists(),
        "compose_path": str(compose_path) if compose_path.exists() else "",
        "running_containers": sorted(running),
        "wiring_complete": wiring_meta.get("status") == "complete" and not missing_tasks,
        "failed_tasks": failed_tasks,
        "missing_tasks": missing_tasks,
        "enabled_services": enabled,
        "available_services": list(services.OPTIONAL.keys()),
    }


@bp.get("/")
def index():
    progress = _detect_progress()

    # Determine the recommended next action
    if not progress["has_state"]:
        next_step = ("welcome.index", "Start a fresh install")
    elif not progress["drive"]:
        next_step = ("drive.index", "Pick your media drive")
    elif not progress["settings"]:
        next_step = ("settings.index", "Configure settings")
    elif not progress["compose_exists"]:
        next_step = ("install.index", "Render compose & install")
    elif not progress["running_containers"]:
        next_step = ("install.index", "Start containers")
    elif progress["missing_tasks"]:
        next_step = ("wiring.index", "Resume wiring")
    else:
        next_step = ("dashboard.index", "Open dashboard")

    return render_template(
        "repair.html",
        step="welcome",  # so stepper highlights the first step
        progress=progress,
        next_endpoint=next_step[0],
        next_label=next_step[1],
    )


@bp.post("/clear")
def clear():
    """Hard reset — wipe wizard state and start over."""
    state.clear()
    return redirect(url_for("welcome.index"), 303)


@bp.post("/rerun-wiring")
def rerun_wiring():
    """Kick off the wiring runner again (idempotent — only retries failed)."""
    wiring_runner.start_wiring()
    return redirect(url_for("wiring.index"), 303)
