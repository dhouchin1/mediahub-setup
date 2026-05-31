"""Flask app factory."""

from __future__ import annotations

import secrets

from flask import Flask

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
