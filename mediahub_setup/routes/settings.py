from __future__ import annotations

from flask import Blueprint, redirect, render_template, request, url_for

from .. import services, state
from ..system_settings import (
    DEFAULT_PORTS,
    detect_gid,
    detect_tz,
    detect_uid,
    generate_password,
)

bp = Blueprint("settings", __name__, url_prefix="/settings")


def _default_form() -> dict:
    """Return form defaults, preferring previously-saved state."""
    saved = state.get("settings") or {}
    ports = saved.get("ports", DEFAULT_PORTS)
    enabled = saved.get("enabled_services") or []
    notifiarr_cfg = saved.get("notifiarr") or {}
    caddy_cfg = saved.get("caddy") or {}
    return {
        "tz": saved.get("tz") or detect_tz(),
        "puid": saved.get("puid", detect_uid()),
        "pgid": saved.get("pgid", detect_gid()),
        "ports": {k: ports.get(k, DEFAULT_PORTS[k]) for k in DEFAULT_PORTS},
        "auto_passwords": saved.get("auto_passwords", True),
        "shared_password": saved.get("shared_password") or generate_password(),
        "enabled_services": enabled,
        "optional_services": services.OPTIONAL,
        "notifiarr": {
            "telegram_bot_token": notifiarr_cfg.get("telegram_bot_token", ""),
            "telegram_chat_id": notifiarr_cfg.get("telegram_chat_id", ""),
        },
        "caddy": {"domain": caddy_cfg.get("domain", "mediahub.local")},
    }


def _validate(form: dict) -> dict[str, str]:
    errors: dict[str, str] = {}

    tz = form.get("tz", "").strip()
    if not tz:
        errors["tz"] = "Timezone is required."

    for field in ("puid", "pgid"):
        raw = form.get(field, "")
        try:
            val = int(raw)
            if val <= 0:
                errors[field] = "Must be a positive integer."
        except (TypeError, ValueError):
            errors[field] = "Must be a positive integer."

    for svc in DEFAULT_PORTS:
        key = f"port_{svc}"
        raw = form.get(key, "")
        if raw == "" or raw is None:
            continue  # not overridden — use default
        try:
            port = int(raw)
            # Privileged ports (1-1023) are allowed for Caddy (80/443) when
            # using Docker Desktop or OrbStack, which handle the binding.
            if not (1 <= port <= 65535):
                errors[key] = "Port must be between 1 and 65535."
        except (TypeError, ValueError):
            errors[key] = "Must be a valid port number."

    return errors


@bp.get("/")
def index():
    defaults = _default_form()
    return render_template(
        "settings.html",
        step="settings",
        errors={},
        **defaults,
    )


@bp.post("/")
def submit():
    f = request.form

    auto_passwords = "auto_passwords" in f

    # Resolve enabled optional services (auto-add prerequisites)
    raw_enabled = f.getlist("enabled_services")
    enabled = services.resolve_dependencies([k for k in raw_enabled if k in services.OPTIONAL])

    # Rebuild a form dict for re-rendering on error
    port_overrides: dict[str, int | str] = {}
    for svc in DEFAULT_PORTS:
        raw = f.get(f"port_{svc}", "").strip()
        port_overrides[svc] = raw if raw else DEFAULT_PORTS[svc]

    form_data = {
        "tz": f.get("tz", "").strip(),
        "puid": f.get("puid", ""),
        "pgid": f.get("pgid", ""),
        "auto_passwords": auto_passwords,
        "shared_password": f.get("shared_password", "").strip() or generate_password(),
        "ports": port_overrides,
        **{f"port_{svc}": f.get(f"port_{svc}", "") for svc in DEFAULT_PORTS},
    }

    errors = _validate(
        {
            "tz": form_data["tz"],
            "puid": form_data["puid"],
            "pgid": form_data["pgid"],
            **{f"port_{svc}": form_data[f"port_{svc}"] for svc in DEFAULT_PORTS},
        }
    )

    if errors:
        return (
            render_template(
                "settings.html",
                step="settings",
                errors=errors,
                tz=form_data["tz"],
                puid=form_data["puid"],
                pgid=form_data["pgid"],
                auto_passwords=form_data["auto_passwords"],
                shared_password=form_data["shared_password"],
                ports=form_data["ports"],
                enabled_services=enabled,
                optional_services=services.OPTIONAL,
                notifiarr={
                    "telegram_bot_token": f.get("notifiarr_telegram_bot_token", "").strip(),
                    "telegram_chat_id": f.get("notifiarr_telegram_chat_id", "").strip(),
                },
                caddy={"domain": f.get("caddy_domain", "mediahub.local").strip()},
            ),
            422,
        )

    # Build final resolved ports (use default if blank)
    final_ports: dict[str, int] = {}
    for svc, default in DEFAULT_PORTS.items():
        raw = f.get(f"port_{svc}", "").strip()
        final_ports[svc] = int(raw) if raw else default

    state.set(
        "settings",
        {
            "tz": form_data["tz"],
            "puid": int(form_data["puid"]),
            "pgid": int(form_data["pgid"]),
            "ports": final_ports,
            "auto_passwords": auto_passwords,
            "shared_password": form_data["shared_password"] if auto_passwords else None,
            "enabled_services": enabled,
            "notifiarr": {
                "telegram_bot_token": f.get("notifiarr_telegram_bot_token", "").strip(),
                "telegram_chat_id": f.get("notifiarr_telegram_chat_id", "").strip(),
            },
            "caddy": {"domain": f.get("caddy_domain", "mediahub.local").strip()},
        },
    )

    return redirect(url_for("install.index"), 303)
