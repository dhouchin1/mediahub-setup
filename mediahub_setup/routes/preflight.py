from flask import Blueprint, render_template

from .. import preflight as checks
from .. import state

bp = Blueprint("preflight", __name__, url_prefix="/preflight")


@bp.get("/")
def index():
    results = checks.run_all()
    status = checks.overall_status(results)
    state.set("preflight", {"status": status, "ran_at": True})
    return render_template(
        "preflight.html",
        step="preflight",
        results=results,
        overall=status,
    )


@bp.post("/rerun")
def rerun():
    """HTMX endpoint — returns just the results partial."""
    results = checks.run_all()
    status = checks.overall_status(results)
    state.set("preflight", {"status": status, "ran_at": True})
    return render_template(
        "_partials/preflight_results.html",
        results=results,
        overall=status,
    )
