from flask import Blueprint, redirect, render_template, request, url_for

from .. import roles, state

bp = Blueprint("welcome", __name__)


@bp.get("/")
def index():
    snap = state.snapshot()
    has_partial = bool(snap.get("drive") or snap.get("settings"))
    has_install = bool((snap.get("install") or {}).get("compose_path"))
    has_wiring = (snap.get("wiring") or {}).get("status") == "complete"
    return render_template(
        "welcome.html",
        step="welcome",
        has_partial=has_partial,
        has_install=has_install,
        has_wiring=has_wiring,
        current_role=roles.current(),
        roles=roles,
    )


@bp.post("/role")
def choose_role():
    """Record the chosen deployment role and advance to preflight."""
    state.set("role", roles.normalize(request.form.get("role")))
    return redirect(url_for("preflight.index"), code=303)
