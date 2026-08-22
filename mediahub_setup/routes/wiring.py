"""Wiring step — auto-configure the *arr stack via REST API."""

from __future__ import annotations

from flask import Blueprint, redirect, render_template, url_for
from flask import Response as FlaskResponse

from .. import roles, wiring_runner

bp = Blueprint("wiring", __name__, url_prefix="/wiring")


@bp.get("/")
def index():
    """Ready screen — shows task checklist before user clicks Start.

    The receiver role has no *arr stack to wire, so it skips straight to Done.
    """
    if roles.current() == roles.RECEIVER:
        return redirect(url_for("done.index"))
    status = wiring_runner.wiring_status()
    return render_template(
        "wiring.html",
        step="wiring",
        task_names=wiring_runner.planned_task_names(),
        phase=status["phase"],
        error=status["error"],
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
        error=status["error"],
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
        error=status["error"],
    )
