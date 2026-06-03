"""Tests for backup/restore — a config tarball round-trip.

No Docker; everything operates on a tmp_path install dir.
"""

from __future__ import annotations

import tarfile

import pytest

from mediahub_setup import backup


def _make_install(install_dir):
    """Lay down a minimal install dir: config tree + compose + env."""
    (install_dir / "config" / "sonarr").mkdir(parents=True)
    (install_dir / "config" / "sonarr" / "config.xml").write_text("<Config/>")
    (install_dir / "docker-compose.yml").write_text("services: {}\n")
    (install_dir / ".env").write_text("TZ=UTC\n")


# --- create_backup ---------------------------------------------------------


def test_create_backup_nothing_to_back_up(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.create_backup(output=tmp_path / "out.tar.gz", install_dir=tmp_path / "empty")


def test_create_backup_writes_archive(tmp_path):
    install = tmp_path / "mediahub"
    _make_install(install)
    out = tmp_path / "bk.tar.gz"

    path = backup.create_backup(output=out, install_dir=install)

    assert path == out
    assert out.is_file()
    with tarfile.open(out) as tar:
        names = tar.getnames()
    assert "docker-compose.yml" in names
    assert ".env" in names
    assert "config/sonarr/config.xml" in names


def test_create_backup_skips_absent_members(tmp_path):
    install = tmp_path / "mediahub"
    (install / "config").mkdir(parents=True)
    (install / "config" / "x.txt").write_text("hi")
    # no compose, no .env

    out = backup.create_backup(output=tmp_path / "bk.tar.gz", install_dir=install)
    with tarfile.open(out) as tar:
        names = tar.getnames()
    assert any(n.startswith("config") for n in names)
    assert "docker-compose.yml" not in names


# --- restore_backup --------------------------------------------------------


def test_round_trip(tmp_path):
    src = tmp_path / "src"
    _make_install(src)
    archive = backup.create_backup(output=tmp_path / "bk.tar.gz", install_dir=src)

    dest = tmp_path / "dest"
    restored = backup.restore_backup(archive, install_dir=dest)

    assert "config" in restored
    assert (dest / "config" / "sonarr" / "config.xml").read_text() == "<Config/>"
    assert (dest / "docker-compose.yml").is_file()
    assert (dest / ".env").read_text() == "TZ=UTC\n"


def test_restore_refuses_existing_config_without_force(tmp_path):
    src = tmp_path / "src"
    _make_install(src)
    archive = backup.create_backup(output=tmp_path / "bk.tar.gz", install_dir=src)

    dest = tmp_path / "dest"
    (dest / "config").mkdir(parents=True)
    with pytest.raises(FileExistsError):
        backup.restore_backup(archive, install_dir=dest)


def test_restore_force_overwrites(tmp_path):
    src = tmp_path / "src"
    _make_install(src)
    archive = backup.create_backup(output=tmp_path / "bk.tar.gz", install_dir=src)

    dest = tmp_path / "dest"
    (dest / "config").mkdir(parents=True)
    restored = backup.restore_backup(archive, install_dir=dest, force=True)
    assert "config" in restored
    assert (dest / "config" / "sonarr" / "config.xml").is_file()


def test_restore_rejects_foreign_archive(tmp_path):
    foreign = tmp_path / "foreign.tar.gz"
    (tmp_path / "random.txt").write_text("nope")
    with tarfile.open(foreign, "w:gz") as tar:
        tar.add(tmp_path / "random.txt", arcname="random.txt")

    with pytest.raises(ValueError, match="doesn't look like a mediahub backup"):
        backup.restore_backup(foreign, install_dir=tmp_path / "dest")


def test_restore_missing_archive(tmp_path):
    with pytest.raises(FileNotFoundError):
        backup.restore_backup(tmp_path / "nope.tar.gz", install_dir=tmp_path / "dest")
