"""Flask app factory."""

from __future__ import annotations

import secrets

from flask import Flask

from .routes import register_blueprints

WIZARD_STEPS = [
    ("welcome", "Welcome"),
    ("preflight", "Preflight"),
    ("drive", "Drive"),
    ("settings", "Settings"),
    ("install", "Install"),
    ("wiring", "Wire-up"),
    ("done", "Done"),
]


def create_app() -> Flask:
    app = Flask(__name__)
    # Local-only server; key just needs to exist for session cookies.
    app.secret_key = secrets.token_urlsafe(32)
    app.config["WIZARD_STEPS"] = WIZARD_STEPS

    @app.context_processor
    def inject_steps() -> dict:
        def step_index(step_key: str | None) -> int:
            if not step_key:
                return -1
            for i, (k, _) in enumerate(WIZARD_STEPS):
                if k == step_key:
                    return i
            return -1

        return {"wizard_steps": WIZARD_STEPS, "step_index": step_index}

    register_blueprints(app)
    return app
