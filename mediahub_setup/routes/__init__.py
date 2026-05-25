"""Wizard route blueprints."""

from __future__ import annotations

from flask import Flask

from . import dashboard, done, drive, install, preflight, repair, settings, welcome, wiring


def register_blueprints(app: Flask) -> None:
    app.register_blueprint(welcome.bp)
    app.register_blueprint(preflight.bp)
    app.register_blueprint(drive.bp)
    app.register_blueprint(settings.bp)
    app.register_blueprint(install.bp)
    app.register_blueprint(wiring.bp)
    app.register_blueprint(done.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(repair.bp)
