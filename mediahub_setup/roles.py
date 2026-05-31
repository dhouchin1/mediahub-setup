"""Deployment roles for the wizard.

A run targets one of three topologies, stored in wizard state under the
``"role"`` key:

* ``all_in_one`` (**default**) — the whole stack on one machine. This is
  the original behaviour; nothing about it changes.
* ``seedbox`` — a remote Linux VPS running the acquisition stack
  (qBittorrent + Sonarr/Radarr/Prowlarr) plus Syncthing in **Send-Only**
  mode, replicating the organised library home. Web UIs bind to loopback
  (reach them over Tailscale); torrent egress can route through a VPN.
* ``receiver`` — a home machine running **only** Syncthing in
  **Receive-Only** mode (with versioning forced on) to hold the synced
  media library for local playback. No *arr stack.

Keeping the role logic here avoids sprinkling string literals across the
routes, the compose renderer and the wiring runner.
"""

from __future__ import annotations

from . import state

ALL_IN_ONE = "all_in_one"
SEEDBOX = "seedbox"
RECEIVER = "receiver"

VALID = (ALL_IN_ONE, SEEDBOX, RECEIVER)

# Human-facing labels + one-liners for the welcome picker / Done page.
LABELS: dict[str, str] = {
    ALL_IN_ONE: "All-in-one (this machine)",
    SEEDBOX: "Remote seedbox (VPS)",
    RECEIVER: "Home receiver (sync target)",
}
DESCRIPTIONS: dict[str, str] = {
    ALL_IN_ONE: "Download, organise and play everything on this one machine.",
    SEEDBOX: "Run the download stack on a remote VPS and sync the library home.",
    RECEIVER: "Receive the synced library from a seedbox and play it locally.",
}

# Tolerate hyphenated / spaced / alias spellings from the CLI and forms.
_ALIASES: dict[str, str] = {
    "allinone": ALL_IN_ONE,
    "all": ALL_IN_ONE,
    "local": ALL_IN_ONE,
    "server": SEEDBOX,
    "vps": SEEDBOX,
    "home": RECEIVER,
    "client": RECEIVER,
}


def normalize(value: str | None) -> str:
    """Coerce arbitrary input to a canonical role, defaulting to all-in-one."""
    if not value:
        return ALL_IN_ONE
    v = value.strip().lower().replace("-", "_").replace(" ", "_")
    if v in VALID:
        return v
    return _ALIASES.get(v.replace("_", ""), _ALIASES.get(v, ALL_IN_ONE))


def current() -> str:
    """The role for this wizard run (from state), normalised."""
    return normalize(state.get("role"))


def label(role: str) -> str:
    return LABELS.get(role, LABELS[ALL_IN_ONE])


def installs_arr(role: str) -> bool:
    """Whether this role installs and wires the core *arr acquisition stack."""
    return role in (ALL_IN_ONE, SEEDBOX)


def is_server(role: str) -> bool:
    """Whether this role is a remote/public host whose service web UIs must
    not bind to ``0.0.0.0`` — bind to loopback and reach them over Tailscale
    (or via the Caddy local-mode allowlist) instead.
    """
    return role == SEEDBOX


def forces_syncthing(role: str) -> bool:
    """Roles for which Syncthing is always part of the install."""
    return role in (SEEDBOX, RECEIVER)


def syncthing_folder_type(role: str) -> str | None:
    """The Syncthing folder type implied by the role, or ``None`` if Syncthing
    is not part of the role by default.

    ``sendonly`` on the seedbox (authoritative source), ``receiveonly`` on the
    home receiver (which additionally forces versioning — see syncthing_client).
    """
    return {SEEDBOX: "sendonly", RECEIVER: "receiveonly"}.get(role)


# Step flows. base.html consumes a list of ``(key, label)`` tuples and calls
# step_index(step_key); these lists are the single source of truth for both.
_STEPS_FULL: list[tuple[str, str]] = [
    ("welcome", "Welcome"),
    ("preflight", "Preflight"),
    ("drive", "Drive"),
    ("settings", "Settings"),
    ("install", "Install"),
    ("wiring", "Wire-up"),
    ("done", "Done"),
]
# The receiver has no *arr to wire, so the Wire-up step is dropped.
_STEPS_RECEIVER: list[tuple[str, str]] = [step for step in _STEPS_FULL if step[0] != "wiring"]


def steps_for(role: str) -> list[tuple[str, str]]:
    """The wizard step list for the given role."""
    if role == RECEIVER:
        return list(_STEPS_RECEIVER)
    return list(_STEPS_FULL)


def has_step(role: str, step_key: str) -> bool:
    """Whether *step_key* is part of the flow for *role*."""
    return any(k == step_key for k, _ in steps_for(role))
