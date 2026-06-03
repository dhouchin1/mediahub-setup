"""Backup & restore a deployment's configuration.

Every service persists its state under ``~/mediahub/config/<service>`` (bind
mounts in the rendered compose), alongside the rendered ``docker-compose.yml``
and ``.env``. Those three things fully describe a deployment — the media
library lives elsewhere and is intentionally **not** included. This module
tarballs them for safe-keeping and restores them onto a fresh machine, the
CLI counterpart to "copy ~/mediahub/config somewhere safe".

``create_backup`` writes a ``.tar.gz``; ``restore_backup`` extracts one back
into the install dir (using tarfile's ``data`` filter so a malicious archive
can't escape the target). Stopping the stack first (``mediahub-setup down``)
gives the most consistent snapshot of the live SQLite databases.
"""

from __future__ import annotations

import tarfile
from datetime import datetime
from pathlib import Path

from .docker_ops import INSTALL_DIR

# What a backup captures, relative to the install dir. Anything absent is just
# skipped — a config-only backup (no compose yet) is still useful.
BACKUP_MEMBERS = ("config", "docker-compose.yml", ".env")

# An archive must contain at least one of these to be recognised as ours.
_MARKERS = ("config", "docker-compose.yml")


def _default_output() -> Path:
    """Timestamped archive name in the current working directory."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path.cwd() / f"mediahub-backup-{stamp}.tar.gz"


def create_backup(output: str | Path | None = None, install_dir: Path | None = None) -> Path:
    """Tar.gz the deployment's config + compose + env. Returns the archive path.

    Raises ``FileNotFoundError`` if the install dir has nothing to back up.
    """
    install_dir = Path(install_dir or INSTALL_DIR)
    present = [m for m in BACKUP_MEMBERS if (install_dir / m).exists()]
    if not present:
        raise FileNotFoundError(
            f"Nothing to back up in {install_dir} — run the wizard/install first."
        )

    out = Path(output).expanduser() if output else _default_output()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(out, "w:gz") as tar:
        for member in present:
            # arcname keeps paths relative so restore lands in any install dir.
            tar.add(install_dir / member, arcname=member)
    return out


def _is_mediahub_archive(tar: tarfile.TarFile) -> bool:
    """True if the archive's top-level entries look like a mediahub backup."""
    tops = {Path(n).parts[0] for n in tar.getnames() if n and not n.startswith("/")}
    return any(marker in tops for marker in _MARKERS)


def restore_backup(
    archive: str | Path, install_dir: Path | None = None, *, force: bool = False
) -> list[str]:
    """Extract a backup into the install dir. Returns the top-level members restored.

    Refuses (``FileExistsError``) to overwrite an existing ``config/`` unless
    *force* is given, and rejects (``ValueError``) an archive that isn't a
    recognised mediahub backup or one that contains unsafe paths.
    """
    archive = Path(archive).expanduser()
    if not archive.is_file():
        raise FileNotFoundError(f"Backup archive not found: {archive}")
    install_dir = Path(install_dir or INSTALL_DIR)

    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
        if not _is_mediahub_archive(tar):
            raise ValueError(
                f"{archive} doesn't look like a mediahub backup "
                "(no config/ or docker-compose.yml at the top level)."
            )
        for name in names:
            p = Path(name)
            if p.is_absolute() or ".." in p.parts:
                raise ValueError(f"Refusing unsafe path in archive: {name}")

        existing_config = install_dir / "config"
        if existing_config.exists() and not force:
            raise FileExistsError(
                f"{existing_config} already exists. Stop the stack and pass "
                "--force to overwrite, or restore into an empty --install-dir."
            )

        install_dir.mkdir(parents=True, exist_ok=True)
        # Python 3.12: the 'data' filter blocks absolute paths, traversal, and
        # special files — defence in depth on top of the check above.
        tar.extractall(install_dir, filter="data")

    tops = sorted({Path(n).parts[0] for n in names if n and not n.startswith("/")})
    return tops
