"""External drive discovery.

Uses `diskutil list -plist external` to enumerate external drives,
then enriches each with filesystem info and write-status via a
temp-file probe (falling back to mount-flag inspection if the probe
is denied).
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field


@dataclass
class DriveInfo:
    name: str
    mount_path: str
    filesystem: str
    total_bytes: int
    free_bytes: int
    writable: bool
    # extra metadata fields, populated where available
    bsd_name: str = ""
    partitions: list[dict] = field(default_factory=list)

    @property
    def total_gb(self) -> float:
        return self.total_bytes / 1_000_000_000

    @property
    def free_gb(self) -> float:
        return self.free_bytes / 1_000_000_000

    @property
    def status(self) -> str:
        """Colour tier: green / amber / red."""
        if not self.writable:
            return "red"
        if self.free_gb < 50:
            return "amber"
        return "green"


def _run_diskutil() -> str:
    """Run diskutil and return stdout. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ["diskutil", "list", "-plist", "external"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return ""


def _run_diskutil_info(bsd_name: str) -> dict:
    """Return parsed plist from `diskutil info -plist <bsd_name>`.

    Returns an empty dict on any failure.
    """
    try:
        result = subprocess.run(
            ["diskutil", "info", "-plist", bsd_name],
            capture_output=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            return plistlib.loads(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError, plistlib.InvalidFileException):
        pass
    return {}


def _parse_diskutil_plist(xml: str) -> list[dict]:
    """Parse `diskutil list -plist external` output.

    Returns a list of partition dicts (those that have a MountPoint),
    each with at least these keys (may have more from diskutil):
      - Content          : filesystem type string, e.g. "APFS", "ExFAT"
      - MountPoint       : e.g. "/Volumes/MyDrive"
      - VolumeName       : e.g. "MyDrive"
      - DiskIdentifier   : e.g. "disk4s1"
      - Size             : int bytes (may be 0 if diskutil didn't provide)

    Raises ValueError if `xml` is not parseable as a plist.
    """
    if not xml.strip():
        return []

    if isinstance(xml, str):
        data = plistlib.loads(xml.encode())
    else:
        data = plistlib.loads(xml)

    # Top-level keys: AllDisks, AllDisksAndPartitions, VolumesFromDisks
    all_disks_and_partitions = data.get("AllDisksAndPartitions", [])

    partitions_out: list[dict] = []
    for disk in all_disks_and_partitions:
        # A disk entry may itself be mounted (e.g. an exFAT flash drive with
        # a single partition that IS the disk).  Recurse into Partitions too.
        entries = [disk] + disk.get("Partitions", []) + disk.get("APFSVolumes", [])
        for entry in entries:
            mount = entry.get("MountPoint", "")
            if mount:
                partitions_out.append(
                    {
                        "Content": entry.get("Content", ""),
                        "MountPoint": mount,
                        "VolumeName": entry.get("VolumeName", entry.get("MountPoint", "")),
                        "DiskIdentifier": entry.get("DiskIdentifier", ""),
                        "Size": entry.get("Size", 0),
                    }
                )

    return partitions_out


def _detect_writable(mount_path: str, filesystem: str) -> bool:
    """Return True if we can write to mount_path.

    Strategy:
    1. NTFS is always read-only on stock macOS — short-circuit to False.
    2. Otherwise try to create + delete a temp file inside mount_path.
       Fall back to os.access check if the probe throws unexpectedly.
    """
    fs_upper = filesystem.upper()
    if "NTFS" in fs_upper:
        return False

    try:
        fd, tmp_path = tempfile.mkstemp(prefix=".mediahub_write_probe_", dir=mount_path)
        os.close(fd)
        os.unlink(tmp_path)
        return True
    except OSError:
        pass

    # Secondary fallback: os.access
    return os.access(mount_path, os.W_OK)


def _format_filesystem(raw: str) -> str:
    """Normalise content/filesystem strings to a human label."""
    mapping = {
        "APFS": "APFS",
        "Apple_APFS": "APFS",
        "ExFAT": "exFAT",
        "FAT32": "FAT32",
        "MSDOS": "FAT32",
        "NTFS": "NTFS",
        "HFS+": "HFS+",
        "Apple_HFS": "HFS+",
        "EXT4": "ext4",
        "EXT3": "ext3",
    }
    upper = raw.upper()
    for key, label in mapping.items():
        if key.upper() in upper:
            return label
    return raw or "Unknown"


def list_drives() -> list[DriveInfo]:
    """Enumerate writable/readable external drives.

    Returns an empty list (never raises) so the UI always has something
    to show even when diskutil fails or no drives are attached.
    """
    xml = _run_diskutil()
    try:
        partitions = _parse_diskutil_plist(xml)
    except (ValueError, plistlib.InvalidFileException):
        partitions = []

    drives: list[DriveInfo] = []
    seen_mounts: set[str] = set()

    for p in partitions:
        mount = p.get("MountPoint", "")
        if not mount or mount in seen_mounts:
            continue
        seen_mounts.add(mount)

        # Skip the macOS system / boot volumes.
        if mount in ("/", "/System/Volumes/Data", "/private/var/vm"):
            continue

        # Filesystem: prefer diskutil info (more precise) then fall back to
        # what _parse_diskutil_plist found.
        raw_fs = p.get("Content", "")
        bsd = p.get("DiskIdentifier", "")

        if bsd:
            info = _run_diskutil_info(bsd)
            # FilesystemType is the most accurate field
            raw_fs = info.get("FilesystemType", raw_fs) or raw_fs

        filesystem = _format_filesystem(raw_fs)

        name = p.get("VolumeName", "") or os.path.basename(mount) or mount

        try:
            usage = shutil.disk_usage(mount)
            total_bytes = usage.total
            free_bytes = usage.free
        except OSError:
            total_bytes = p.get("Size", 0)
            free_bytes = 0

        writable = _detect_writable(mount, filesystem)

        drives.append(
            DriveInfo(
                name=name,
                mount_path=mount,
                filesystem=filesystem,
                total_bytes=total_bytes,
                free_bytes=free_bytes,
                writable=writable,
                bsd_name=bsd,
            )
        )

    return drives


def fmt_gb(n_bytes: int) -> str:
    """Format bytes as a human-readable GB string."""
    gb = n_bytes / 1_000_000_000
    if gb >= 1000:
        return f"{gb / 1000:.1f} TB"
    if gb >= 1:
        return f"{gb:.0f} GB"
    mb = n_bytes / 1_000_000
    return f"{mb:.0f} MB"
