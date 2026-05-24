from flask import Blueprint, render_template

bp = Blueprint("welcome", __name__)


@bp.get("/")
def index():
    return render_template("welcome.html", step="welcome")
