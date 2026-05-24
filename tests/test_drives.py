"""Tests for mediahub_setup.drives.

Focuses on pure-Python helpers so CI doesn't need external drives or
diskutil. The list_drives() integration function is exercised only via
a structural smoke test (it must never raise).
"""

from __future__ import annotations

import plistlib

import pytest

from mediahub_setup.drives import DriveInfo, _parse_diskutil_plist, fmt_gb

# ---------------------------------------------------------------------------
# Minimal valid plist produced by `diskutil list -plist external`
# This fixture mimics a machine with two external drives:
#   - disk4  : APFS container with one volume at /Volumes/BackupDrive
#   - disk5  : exFAT single-partition drive at /Volumes/MyFlash
# ---------------------------------------------------------------------------

SAMPLE_PLIST = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>AllDisks</key>
  <array>
    <string>disk4</string>
    <string>disk4s1</string>
    <string>disk5</string>
    <string>disk5s1</string>
  </array>
  <key>AllDisksAndPartitions</key>
  <array>
    <!-- APFS container disk with one APFSVolume -->
    <dict>
      <key>DiskIdentifier</key>
      <string>disk4</string>
      <key>Size</key>
      <integer>2000398934016</integer>
      <key>Content</key>
      <string>GUID_partition_scheme</string>
      <key>APFSVolumes</key>
      <array>
        <dict>
          <key>DiskIdentifier</key>
          <string>disk4s1</string>
          <key>Content</key>
          <string>Apple_APFS</string>
          <key>VolumeName</key>
          <string>BackupDrive</string>
          <key>MountPoint</key>
          <string>/Volumes/BackupDrive</string>
          <key>Size</key>
          <integer>2000398934016</integer>
        </dict>
      </array>
    </dict>
    <!-- exFAT flash drive with a single partition -->
    <dict>
      <key>DiskIdentifier</key>
      <string>disk5</string>
      <key>Size</key>
      <integer>64023257088</integer>
      <key>Content</key>
      <string>GUID_partition_scheme</string>
      <key>Partitions</key>
      <array>
        <dict>
          <key>DiskIdentifier</key>
          <string>disk5s1</string>
          <key>Content</key>
          <string>ExFAT</string>
          <key>VolumeName</key>
          <string>MyFlash</string>
          <key>MountPoint</key>
          <string>/Volumes/MyFlash</string>
          <key>Size</key>
          <integer>64023257088</integer>
        </dict>
      </array>
    </dict>
  </array>
  <key>VolumesFromDisks</key>
  <array>
    <string>BackupDrive</string>
    <string>MyFlash</string>
  </array>
</dict>
</plist>
"""

# A plist with NO mounted volumes (unmounted drives)
EMPTY_VOLUMES_PLIST = b"""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>AllDisks</key>
  <array/>
  <key>AllDisksAndPartitions</key>
  <array/>
  <key>VolumesFromDisks</key>
  <array/>
</dict>
</plist>
"""


class TestParseDiskutilPlist:
    def test_returns_two_volumes(self):
        result = _parse_diskutil_plist(SAMPLE_PLIST.decode())
        mounts = [p["MountPoint"] for p in result]
        assert "/Volumes/BackupDrive" in mounts
        assert "/Volumes/MyFlash" in mounts

    def test_volume_names(self):
        result = _parse_diskutil_plist(SAMPLE_PLIST.decode())
        names = {p["MountPoint"]: p["VolumeName"] for p in result}
        assert names["/Volumes/BackupDrive"] == "BackupDrive"
        assert names["/Volumes/MyFlash"] == "MyFlash"

    def test_content_fields(self):
        result = _parse_diskutil_plist(SAMPLE_PLIST.decode())
        by_mount = {p["MountPoint"]: p for p in result}
        assert by_mount["/Volumes/BackupDrive"]["Content"] == "Apple_APFS"
        assert by_mount["/Volumes/MyFlash"]["Content"] == "ExFAT"

    def test_empty_plist_returns_empty_list(self):
        result = _parse_diskutil_plist(EMPTY_VOLUMES_PLIST.decode())
        assert result == []

    def test_empty_string_returns_empty_list(self):
        result = _parse_diskutil_plist("")
        assert result == []

    def test_invalid_plist_raises_value_error(self):
        with pytest.raises(plistlib.InvalidFileException):
            _parse_diskutil_plist("not a plist at all %%##")

    def test_disk_identifier_present(self):
        result = _parse_diskutil_plist(SAMPLE_PLIST.decode())
        by_mount = {p["MountPoint"]: p for p in result}
        assert by_mount["/Volumes/BackupDrive"]["DiskIdentifier"] == "disk4s1"
        assert by_mount["/Volumes/MyFlash"]["DiskIdentifier"] == "disk5s1"

    def test_size_present(self):
        result = _parse_diskutil_plist(SAMPLE_PLIST.decode())
        for p in result:
            assert isinstance(p["Size"], int)
            assert p["Size"] > 0


class TestFmtGb:
    def test_terabytes(self):
        assert "TB" in fmt_gb(2_000_398_934_016)

    def test_gigabytes(self):
        s = fmt_gb(500_000_000_000)
        assert "GB" in s
        assert "500" in s

    def test_megabytes(self):
        s = fmt_gb(512_000_000)
        assert "MB" in s

    def test_zero(self):
        # should not raise
        s = fmt_gb(0)
        assert "MB" in s or "GB" in s


class TestDriveInfoProperties:
    def _make(self, total_bytes: int, free_bytes: int, writable: bool = True) -> DriveInfo:
        return DriveInfo(
            name="TestDrive",
            mount_path="/Volumes/TestDrive",
            filesystem="APFS",
            total_bytes=total_bytes,
            free_bytes=free_bytes,
            writable=writable,
        )

    def test_total_gb(self):
        d = self._make(1_000_000_000_000, 500_000_000_000)
        assert abs(d.total_gb - 1000.0) < 0.1

    def test_free_gb(self):
        d = self._make(1_000_000_000_000, 500_000_000_000)
        assert abs(d.free_gb - 500.0) < 0.1

    def test_status_green(self):
        d = self._make(2_000_000_000_000, 100_000_000_000, writable=True)
        assert d.status == "green"

    def test_status_amber_small_free(self):
        # 49 GB free — below the 50 GB threshold
        d = self._make(100_000_000_000, 49_000_000_000, writable=True)
        assert d.status == "amber"

    def test_status_red_not_writable(self):
        d = self._make(1_000_000_000_000, 500_000_000_000, writable=False)
        assert d.status == "red"


class TestListDrivesSmokeTest:
    """list_drives() must never raise, even with no external drives."""

    def test_returns_list(self):
        from mediahub_setup.drives import list_drives

        result = list_drives()
        assert isinstance(result, list)

    def test_every_entry_is_drive_info(self):
        from mediahub_setup.drives import list_drives

        for d in list_drives():
            assert isinstance(d, DriveInfo)
            assert d.mount_path
            assert d.name
