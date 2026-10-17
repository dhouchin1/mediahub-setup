"""Wiring step — auto-configure the *arr stack via REST API."""

from __future__ import annotations

from flask import Blueprint, render_template
from flask import Response as FlaskResponse

from .. import wiring_runner

bp = Blueprint("wiring", __name__, url_prefix="/wiring")


@bp.get("/")
def index():
    """Ready screen — shows task checklist before user clicks Start.

    Every role goes through wiring: the receiver has no *arr stack, but its
    task plan still carries the Syncthing steps (receive-only folder, forced
    versioning, device pairing) — skipping to Done left a wizard-installed
    receiver entirely unconfigured, while the headless path wired it fine.
    """
    status = wiring_runner.wiring_status()
    return render_template(
        "wiring.html",
        step="wiring",
        task_names=wiring_runner.planned_task_names(),
        phase=status["phase"],
        tasks=status["tasks"],
    )


@bp.post("/start")
def start() -> FlaskResponse:
    """Spawn the background wiring thread; return 202."""
    wiring_runner.start_wiring()
    status = wiring_runner.wiring_status()
    partial = render_template(
        "_partials/wiring_status.html",
        tasks=status["tasks"],
        phase=status["phase"],
    )
    return FlaskResponse(partial, status=202)


@bp.get("/status")
def poll_status() -> str:
    """HTMX polling endpoint — returns the task-list partial."""
    status = wiring_runner.wiring_status()
    return render_template(
        "_partials/wiring_status.html",
        tasks=status["tasks"],
        phase=status["phase"],
    )
