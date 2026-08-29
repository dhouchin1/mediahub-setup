"""Flask app factory."""

from __future__ import annotations

import secrets
from urllib.parse import urlsplit

from flask import Flask, request

from . import roles
from .routes import register_blueprints

# Canonical full flow (back-compat alias; the per-request stepper is
# role-aware via roles.steps_for below).
WIZARD_STEPS = roles.steps_for(roles.ALL_IN_ONE)


def create_app() -> Flask:
    app = Flask(__name__)
    # Local-only server; key just needs to exist for session cookies.
    app.secret_key = secrets.token_urlsafe(32)
    app.config["WIZARD_STEPS"] = WIZARD_STEPS

    @app.before_request
    def reject_cross_origin_writes() -> tuple[str, int] | None:
        # The wizard's POST handlers start installs, rewrite settings, and
        # wipe state, and they authenticate nothing — a hostile web page can
        # fire "simple" cross-origin form POSTs at localhost without any
        # CORS preflight. Browsers attach an Origin header to POSTs, so a
        # present-but-mismatched Origin is a reliable drive-by signature.
        # Non-browser clients (curl, tests) send no Origin and are unaffected.
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return None
        origin = request.headers.get("Origin")
        if not origin:
            return None
        # 'Origin: null' (sandboxed iframes, file://) is itself a drive-by
        # vector, so it does not get a pass.
        if origin == "null" or urlsplit(origin).netloc != request.host:
            return "Cross-origin request rejected.", 403
        return None

    @app.context_processor
    def inject_steps() -> dict:
        # Recomputed per request so the stepper reflects the chosen role
        # (e.g. the receiver flow omits the Wire-up step).
        steps = roles.steps_for(roles.current())

        def step_index(step_key: str | None) -> int:
            if not step_key:
                return -1
            for i, (k, _) in enumerate(steps):
                if k == step_key:
                    return i
            return -1

        return {"wizard_steps": steps, "step_index": step_index}

    register_blueprints(app)
    return app
