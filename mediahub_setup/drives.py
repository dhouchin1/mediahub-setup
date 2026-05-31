"""Drive discovery.

On macOS, uses `diskutil list -plist external` to enumerate external
drives. On Linux (e.g. a VPS), uses `lsblk --json` (falling back to
parsing `/proc/mounts`) to enumerate mounted data filesystems. Each
drive is enriched with filesystem info and write-status via a temp-file
probe. Selection dispatches on the OS via :mod:`platform_detect`.
"""

from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import platform_detect


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
    1. On macOS, NTFS is always read-only on the stock kernel —
       short-circuit to False. (On Linux, ntfs-3g usually mounts it
       writable, so we let the probe decide there.)
    2. Otherwise try to create + delete a temp file inside mount_path.
       Fall back to os.access check if the probe throws unexpectedly.
    """
    fs_upper = filesystem.upper()
    if "NTFS" in fs_upper and platform_detect.is_macos():
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
        "EXT2": "ext2",
        "BTRFS": "Btrfs",
        "XFS": "XFS",
        "ZFS": "ZFS",
        "VFAT": "FAT32",
        "F2FS": "F2FS",
    }
    upper = raw.upper()
    for key, label in mapping.items():
        if key.upper() in upper:
            return label
    return raw or "Unknown"


def _list_drives_macos() -> list[DriveInfo]:
    """Enumerate writable/readable external drives via diskutil (macOS).

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


# ---------------------------------------------------------------------------
# Linux backend (lsblk, with a /proc/mounts fallback)
# ---------------------------------------------------------------------------

# Pseudo / virtual filesystems that are never a media drive.
_VIRTUAL_FS = {
    "squashfs",
    "overlay",
    "tmpfs",
    "devtmpfs",
    "proc",
    "sysfs",
    "ramfs",
    "autofs",
    "cgroup",
    "cgroup2",
    "mqueue",
    "debugfs",
    "tracefs",
    "fusectl",
    "configfs",
    "efivarfs",
    "bpf",
    "pstore",
    "securityfs",
}
# Mount points to skip on Linux: the OS lives here, not media. The data disk
# on a tiny VPS may be `/` itself — in that case use the manual-path input.
_LINUX_SKIP_PREFIXES = ("/proc", "/sys", "/run", "/dev", "/snap", "/var/lib/docker")
_LINUX_SKIP_EXACT = {"/", "/boot", "/boot/efi", "/boot/firmware", "[SWAP]", ""}


def _coerce_int(value: object) -> int:
    """lsblk may return SIZE as an int (newer) or a string (older)."""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _mount_of(dev: dict) -> str:
    """Return a device's mount point, tolerating both the singular
    ``mountpoint`` and the newer plural ``mountpoints`` lsblk fields."""
    mount = dev.get("mountpoint")
    if not mount:
        mounts = dev.get("mountpoints")
        if isinstance(mounts, list):
            mount = next((m for m in mounts if m), None)
    return mount or ""


def _is_skippable_linux_mount(mount: str) -> bool:
    if mount in _LINUX_SKIP_EXACT:
        return True
    return any(mount == p or mount.startswith(p + "/") for p in _LINUX_SKIP_PREFIXES)


def _flatten_lsblk(devices: list[dict] | None):
    """Yield every device + nested child from lsblk's tree."""
    for dev in devices or []:
        yield dev
        yield from _flatten_lsblk(dev.get("children"))


def _drive_from_mount(mount: str, *, fstype_raw: str, name: str, ro: bool) -> DriveInfo:
    """Build a DriveInfo for a mounted Linux filesystem."""
    filesystem = _format_filesystem(fstype_raw)
    try:
        usage = shutil.disk_usage(mount)
        total_bytes, free_bytes = usage.total, usage.free
    except OSError:
        total_bytes = free_bytes = 0
    writable = False if ro else _detect_writable(mount, filesystem)
    return DriveInfo(
        name=name or os.path.basename(mount) or mount,
        mount_path=mount,
        filesystem=filesystem,
        total_bytes=total_bytes,
        free_bytes=free_bytes,
        writable=writable,
    )


def _parse_lsblk(data: dict) -> list[DriveInfo]:
    """Turn parsed `lsblk --json` output into DriveInfo entries.

    Pure function (no subprocess) so tests can inject a sample payload.
    """
    drives: list[DriveInfo] = []
    seen: set[str] = set()
    for dev in _flatten_lsblk(data.get("blockdevices", [])):
        if dev.get("type") not in ("disk", "part", "lvm", "crypt"):
            continue
        mount = _mount_of(dev)
        if _is_skippable_linux_mount(mount) or mount in seen:
            continue
        fstype = (dev.get("fstype") or "").lower()
        if fstype in _VIRTUAL_FS:
            continue
        seen.add(mount)
        ro = dev.get("ro") in (True, 1, "1")
        drives.append(
            _drive_from_mount(
                mount,
                fstype_raw=dev.get("fstype") or "",
                name=dev.get("label") or "",
                ro=ro,
            )
        )
    return drives


def _run_lsblk() -> str:
    """Run lsblk and return JSON stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            [
                "lsblk",
                "--json",
                "--paths",
                "--bytes",
                "-o",
                "NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT,RM,RO,LABEL",
            ],
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


def _unescape_proc_mount(field_value: str) -> str:
    """Decode the octal escapes /proc/mounts uses for spaces etc."""
    for esc, char in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        field_value = field_value.replace(esc, char)
    return field_value


def _list_drives_proc_mounts() -> list[DriveInfo]:
    """Fallback enumeration when lsblk is unavailable (minimal images)."""
    drives: list[DriveInfo] = []
    seen: set[str] = set()
    try:
        lines = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        return drives
    for line in lines:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = parts[0], _unescape_proc_mount(parts[1]), parts[2]
        if not device.startswith("/dev/"):
            continue
        if fstype.lower() in _VIRTUAL_FS:
            continue
        if _is_skippable_linux_mount(mount) or mount in seen:
            continue
        seen.add(mount)
        ro = len(parts) >= 4 and "ro" in parts[3].split(",")
        drives.append(
            _drive_from_mount(mount, fstype_raw=fstype, name=os.path.basename(mount), ro=ro)
        )
    return drives


def _list_drives_linux() -> list[DriveInfo]:
    """Enumerate mounted data filesystems on Linux."""
    raw = _run_lsblk()
    if raw:
        try:
            drives = _parse_lsblk(json.loads(raw))
            if drives:
                return drives
        except (ValueError, KeyError, TypeError):
            pass
    return _list_drives_proc_mounts()


def drive_from_path(path: str) -> DriveInfo | None:
    """Build a DriveInfo for an arbitrary host directory (manual entry).

    Returns None if *path* isn't an existing directory. Used by the drive
    step's manual-path input — primarily for headless Linux servers where
    the media location is a plain folder on the root disk rather than a
    separately-mounted drive.
    """
    if not path:
        return None
    p = Path(path).expanduser()
    if not p.is_dir():
        return None
    mount = str(p)
    try:
        usage = shutil.disk_usage(mount)
        total_bytes, free_bytes = usage.total, usage.free
    except OSError:
        total_bytes = free_bytes = 0
    return DriveInfo(
        name=p.name or mount,
        mount_path=mount,
        filesystem="directory",
        total_bytes=total_bytes,
        free_bytes=free_bytes,
        writable=_detect_writable(mount, ""),
    )


def list_drives() -> list[DriveInfo]:
    """Enumerate writable/readable data drives for the current OS.

    Never raises — returns an empty list when nothing is found so the UI
    always has something to render.
    """
    if platform_detect.is_linux():
        return _list_drives_linux()
    return _list_drives_macos()


def fmt_gb(n_bytes: int) -> str:
    """Format bytes as a human-readable GB string."""
    gb = n_bytes / 1_000_000_000
    if gb >= 1000:
        return f"{gb / 1000:.1f} TB"
    if gb >= 1:
        return f"{gb:.0f} GB"
    mb = n_bytes / 1_000_000
    return f"{mb:.0f} MB"
