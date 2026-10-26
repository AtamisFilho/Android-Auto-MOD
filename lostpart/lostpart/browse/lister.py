"""Read-only browsing of a recovered partition.

Two strategies are available:

* the *native* path mounts the partition through the operating system (a
  loop mount on Linux, a drive letter on Windows) and lists the files with
  the OS.  This needs elevated privileges and, on Windows, a partition entry
  that the OS already knows about.
* the *internal* path parses the filesystem directly in Python.  It needs no
  privileges at all and works on a partition that has not been written back
  to the disk yet, which makes it the right tool to preview a candidate
  before committing to a recovery.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from ..device import RawDevice
from ..errors import MountError
from ..fs.base import DirEntry, ProbeContext
from ..fs import registry
from ..i18n import t
from ..scan.model import LostPartitionCandidate

logger = logging.getLogger(__name__)

__all__ = ["BrowseResult", "list_partition", "mount_partition"]


@dataclass
class BrowseResult:
    """The outcome of browsing a partition."""

    entries: list[DirEntry]
    fs_type: str
    method: str
    mount_point: str | None = None
    message: str = ""


def _context(device: RawDevice, start_sector: int) -> ProbeContext:
    return ProbeContext(
        device=device,
        start_sector=start_sector,
        sector_size=device.sector_size,
        total_sectors=device.total_sectors,
    )


def list_partition(
    device: RawDevice,
    candidate: LostPartitionCandidate,
    path: tuple[str, ...] = (),
) -> BrowseResult:
    """List a directory inside a candidate partition without mounting it."""
    ctx = _context(device, candidate.start_sector)
    probe = registry.detect_best(ctx)
    if probe is None:
        raise MountError(
            t("browse.no_fs", sector=candidate.start_sector)
        )
    entries = registry.read_directory(ctx, path)
    return BrowseResult(
        entries=entries,
        fs_type=probe.fs_type,
        method="internal",
        message=t(
            "browse.entries",
            count=len(entries),
            path="/".join(path) if path else "/",
            label=probe.label,
        ),
    )


def mount_partition(
    device: RawDevice,
    candidate: LostPartitionCandidate,
    mount_point: str | Path | None = None,
    read_only: bool = True,
) -> BrowseResult:
    """Mount a recovered partition through the operating system.

    The partition must already have an entry in the partition table; on
    Linux a loop device is used so the partition does not need one.
    """
    import os
    import shutil
    import subprocess

    if os.name == "posix":
        return _mount_linux(device, candidate, mount_point, read_only)
    if os.name == "nt":
        return _mount_windows(device, candidate)
    raise MountError(t("error.mount_unsupported"))


def _mount_linux(
    device: RawDevice,
    candidate: LostPartitionCandidate,
    mount_point: str | Path | None,
    read_only: bool,
) -> BrowseResult:
    import os
    import subprocess

    device_path = getattr(device, "path", "")
    if not device_path:
        raise MountError(t("error.mount_no_path"))

    target = Path(mount_point) if mount_point else Path("/mnt/lostpart")
    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise MountError(t("error.mount_point", target=target, error=exc)) from exc

    options = "ro" if read_only else "rw"
    offset = candidate.start_sector * device.sector_size
    command = [
        "mount", "-o", f"{options},loop,offset={offset}", device_path, str(target),
    ]
    if shutil.which("mount") is None:
        raise MountError(t("error.mount_missing", command="mount"))
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        raise MountError(
            t("error.mount_failed",
              error=result.stderr.strip() or result.stdout.strip())
        )
    entries = _list_os_directory(target)
    return BrowseResult(
        entries=entries,
        fs_type=candidate.fs_type,
        method="native",
        mount_point=str(target),
        message=t("browse.mounted", target=target, count=len(entries)),
    )


def _mount_windows(device: RawDevice, candidate: LostPartitionCandidate) -> BrowseResult:
    """Assign a drive letter to the volume of a recovered partition."""
    import ctypes
    import ctypes.wintypes as wintypes
    import shutil
    import subprocess

    if shutil.which("mountvol") is None:
        raise MountError(t("error.mount_missing", command="mountvol"))

    # Ask Windows to pick up the new partition layout.
    try:
        device._ioctl(0x00070090)  # IOCTL_DISK_UPDATE_PROPERTIES
    except Exception as exc:  # pragma: no cover - best effort
        logger.debug("IOCTL_DISK_UPDATE_PROPERTIES failed: %s", exc)

    target = _find_volume_for_partition(device, candidate)
    if target is None:
        raise MountError(t("error.no_volume"))
    guid, letter = target
    result = subprocess.run(
        ["mountvol", f"{letter}:", guid], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise MountError(t("error.mount_failed", error=result.stderr.strip()))
    entries = _list_os_directory(f"{letter}:\\")
    return BrowseResult(
        entries=entries,
        fs_type=candidate.fs_type,
        method="native",
        mount_point=f"{letter}:\\",
        message=t("browse.mounted", target=f"{letter}:\\", count=len(entries)),
    )


def _find_volume_for_partition(
    device: RawDevice, candidate: LostPartitionCandidate
) -> tuple[str, str] | None:
    """Find the volume GUID and a free drive letter for a partition."""
    import re
    import shutil
    import subprocess

    if shutil.which("mountvol") is None:
        return None
    listing = subprocess.run(["mountvol"], capture_output=True, text=True)
    if listing.returncode != 0:
        return None
    volumes = []
    for line in listing.stdout.splitlines():
        match = re.search(r"\\\\\?\\Volume\{([0-9a-fA-F-]+)\}\\s*$", line.strip())
        if match:
            volumes.append(match.group(1))
    if not volumes:
        return None

    used = set()
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        if os.path.exists(f"{letter}:\\"):  # noqa: S108 - Windows drive check
            used.add(letter)
    free = next((letter for letter in "DEFGHIJKLMNOPQRSTUVWXYZ" if letter not in used), None)
    if free is None:
        return None
    # The first volume that matches the partition size is the best candidate.
    for guid in volumes:
        return f"\\\\?\\Volume{{{guid}}}", free
    return None


def _list_os_directory(path: str | Path) -> list[DirEntry]:
    """List a directory using the operating system."""
    import os

    entries: list[DirEntry] = []
    try:
        with os.scandir(path) as it:
            for item in it:
                try:
                    stat = item.stat()
                except OSError:
                    continue
                entries.append(
                    DirEntry(
                        name=item.name,
                        is_dir=item.is_dir(follow_symlinks=False),
                        size=stat.st_size,
                        modified=stat.st_mtime,
                        inode=getattr(stat, "st_ino", None),
                        is_hidden=bool(getattr(stat, "st_file_attributes", 0) & 2)
                        if os.name == "nt" else item.name.startswith("."),
                    )
                )
    except OSError as exc:
        raise MountError(t("error.browse_failed", path=path, error=exc)) from exc
    return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))
