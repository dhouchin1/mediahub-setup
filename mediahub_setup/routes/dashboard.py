"""Post-install management dashboard.

Live container health, hardware stats, restart buttons, and an
"update everything" action. Available at /dashboard once the wizard
has finished; also reachable directly so the user can come back to it.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from .. import docker_ops, services, state

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


def _service_meta(container_name: str, ports: dict) -> dict:
    """Look up the catalog entry for a container by its mediahub-* name."""
    key = container_name.removeprefix("mediahub-")
    svc = services.ALL.get(key, {})
    port_key = svc.get("port_key") or ""
    port = ports.get(port_key, svc.get("default_port", 0))
    url_path = svc.get("url_path", "/")
    url = f"http://localhost:{port}{url_path}" if port else ""
    return {
        "key": key,
        "name": svc.get("name", key),
        "role": svc.get("role", ""),
        "color": svc.get("color", "slate"),
        "url": url,
    }


def _build_rows() -> list[dict]:
    """Merge container info + stats + catalog metadata into one list."""
    settings = state.get("settings") or {}
    ports = settings.get("ports") or {}

    containers = docker_ops.list_containers()
    stats = {s["name"]: s for s in docker_ops.docker_stats()}

    rows: list[dict] = []
    for c in containers:
        meta = _service_meta(c["name"], ports)
        st = stats.get(c["name"], {})
        rows.append(
            {
                **meta,
                "container_name": c["name"],
                "image": c["image"],
                "state": c["state"],
                "status": c["status"],
                "cpu_percent": st.get("cpu_percent", 0.0),
                "mem_percent": st.get("mem_percent", 0.0),
                "mem_usage": st.get("mem_usage", ""),
            }
        )
    # Sort: running first (alpha), then stopped (alpha)
    rows.sort(key=lambda r: (r["state"] != "running", r["name"]))
    return rows


@bp.get("/")
def index():
    drive = state.get("drive") or {}
    install = state.get("install") or {}
    mount = drive.get("mount_path") or ""

    rows = _build_rows()
    disk = (
        docker_ops.disk_usage(mount)
        if mount
        else {
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "percent_used": 0.0,
        }
    )
    docker_ok = docker_ops.docker_available()

    return render_template(
        "dashboard.html",
        step="done",  # so the stepper highlights "Done"
        rows=rows,
        disk=disk,
        docker_ok=docker_ok,
        mount_path=mount,
        compose_path=install.get("compose_path", ""),
        update_status=docker_ops.update_status(),
    )


@bp.get("/status")
def status_partial():
    """HTMX polling endpoint — returns just the rows + disk partial."""
    drive = state.get("drive") or {}
    mount = drive.get("mount_path") or ""
    rows = _build_rows()
    disk = (
        docker_ops.disk_usage(mount)
        if mount
        else {
            "total_gb": 0.0,
            "used_gb": 0.0,
            "free_gb": 0.0,
            "percent_used": 0.0,
        }
    )
    return render_template(
        "_partials/dashboard_stats.html",
        rows=rows,
        disk=disk,
    )


@bp.post("/restart")
def restart_container():
    name = (request.form.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "missing name"}), 400
    ok, msg = docker_ops.restart_container(name)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 500)


@bp.get("/logs")
def container_logs():
    name = (request.args.get("name") or "").strip()
    if not name or not name.startswith("mediahub-"):
        return ("Invalid container name", 400)
    try:
        tail = int(request.args.get("tail", "50"))
    except ValueError:
        return ("Invalid tail value", 400)
    # Bound it — the value ends up in `docker logs --tail`.
    tail = max(1, min(tail, 1000))
    return (docker_ops.container_logs(name, tail=tail), 200, {"Content-Type": "text/plain"})


@bp.post("/update-all")
def update_all():
    """Kick off `docker compose pull && docker compose up -d`."""
    docker_ops.compose_update_all()
    return render_template(
        "_partials/dashboard_update.html",
        update_status=docker_ops.update_status(),
    )


@bp.get("/update-status")
def update_status_partial():
    return render_template(
        "_partials/dashboard_update.html",
        update_status=docker_ops.update_status(),
    )
